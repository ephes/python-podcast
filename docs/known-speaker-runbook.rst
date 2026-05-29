Known-Speaker Diarization Deploy & Validation Runbook
=====================================================

This runbook covers shipping contributor known-speaker recognition end to end:
Voxhelm (the known-speaker engine), django-cast (private references + request +
suggestion storage), and python-podcast (integration + deploy). Staging is
deployed first and verified, then production, then real references are added and
quality is validated to >90% on a gold set.

Offline validation already passed: the shipped Voxhelm code path measured
**93.27% all-segment top-1** accuracy on the 1249-segment ``pp_64`` gold set
(99.89% accuracy at 69.98% coverage under the auto-accept policy), with the
known Johannes passage correctly attributed. See
``voxhelm/evals/known_speaker_results.md``.

Deployed-production validation also passed on **two** episodes against
multitrack-derived gold sets: ``pp_64`` (same-episode references, 95.06%
segment-level top-1) and ``pp_62`` "Bytes und Strings" (episode 135, audio 77;
**cross-episode** references taken from ``pp_64`` only — zero eval leakage —
scoring **96.76% time-weighted top-1 / DER 3.24%** full-episode, with public
auto-applied labels 98.56% accurate). The pp_62 run needed no code or config
changes; see ``voxhelm/evals/known_speaker_results.md`` for both metric
definitions and Voxhelm job ids.

0. Prerequisites
----------------

* Hugging Face access for ``pyannote/wespeaker-voxceleb-resnet34-LM`` configured
  on the Voxhelm host (macstudio) — confirmed available.
* Voxhelm ``VOXHELM_ALLOWED_URL_HOSTS`` must include the CloudFront media host so
  source-range reference audio can be fetched.

1. Land the code
----------------

* Voxhelm branch ``known-speaker-diarization`` (commits: known-speaker engine,
  eval harness, review-gate refinement).
* django-cast ``develop`` (commits: private voice references; known-speaker
  request + suggestion storage).
* python-podcast branch ``known-speaker-diarization`` (deploy docs).

Push django-cast ``develop`` and merge/push the Voxhelm and python-podcast
branches so the deploy can pin them::

    cd ~/projects/django-cast && git push origin develop
    cd ~/projects/voxhelm && git push && # open/merge PR
    cd ~/projects/python-podcast && git push -u origin known-speaker-diarization

2. Deploy Voxhelm (staging-equivalent, then production)
-------------------------------------------------------

From ops-control::

    just deploy-one voxhelm HOST=macstudio

Ensure the Voxhelm environment has::

    VOXHELM_DIARIZATION_BACKEND=pyannote
    VOXHELM_HUGGINGFACE_TOKEN=<token with accepted wespeaker terms>
    VOXHELM_ALLOWED_URL_HOSTS=<...,cloudfront media host>

Run ``just check`` in voxhelm before deploying (205 tests, lint, typecheck).

3. Bump django-cast in python-podcast & deploy staging
------------------------------------------------------

::

    cd ~/projects/python-podcast
    uv lock --upgrade-package django-cast      # picks up the pushed develop commit
    git add uv.lock && git commit -m "Bump django-cast for known-speaker diarization"
    just deploy-staging

The deploy runs migrations (including ``cast.0071``) and restarts Gunicorn and
the ``cast_transcripts`` worker. Set in the staging shared environment::

    CAST_VOXHELM_DIARIZATION_ENABLED=true
    CAST_VOXHELM_KNOWN_SPEAKER_ENABLED=true

4. Verify staging through the real flow
---------------------------------------

* In Wagtail, add approved voice references for the expected contributors of a
  test episode (source ranges into earlier-episode mastered audio; mark consent
  confirmed; approve). Clean solo passages work best.
* Generate the transcript from the episode edit page. The ``cast_transcripts``
  worker completes the Voxhelm job asynchronously.
* Confirm a private ``Transcript.speakers`` sidecar is stored and that public
  transcript output shows no speaker names yet (suggestions await review).
* Record the Voxhelm job id and request/result metadata.

5. Deploy production (only after staging works)
-----------------------------------------------

::

    just deploy-production

Set the same ``CAST_VOXHELM_DIARIZATION_ENABLED`` /
``CAST_VOXHELM_KNOWN_SPEAKER_ENABLED`` env in the production shared environment.

6. Add references & validate >90% on the gold set
--------------------------------------------------

* Add approved voice references for the relevant Python Podcast contributors.
* Generate a transcript through Voxhelm for the gold-set episode.
* Inspect the returned ``speakers`` sidecar suggestions.
* Score against the hand-labeled gold set (the known Johannes passage around
  00:38:16-00:38:32 plus representative passages per speaker and short/overlap
  cases). Target: >=90% segment-level top-1 accuracy. Uncertain segments are
  "needs review" and excluded from auto-applied public labels, not counted as
  correct.
* The offline harness ``voxhelm/evals/known_speaker_eval.py`` reproduces the
  measurement locally and is the reference for expected numbers.

7. Evidence to record
----------------------

Commits, migrations applied, deploy commands + ops-control/job ids or URLs,
``just check`` output per repo, Voxhelm request/result metadata, and
before/after quality metrics (anonymous ~77-87% vs known-speaker >90%).

Remaining follow-up
-------------------

The Wagtail review-and-apply path has landed: an editor reviews the private
suggestions and applies the approved labels to public Podlove/DOTe via
``Transcript.apply_known_speaker_suggestions()``. This was exercised on
production for ``pp_62`` (episode 135), so that episode's public transcript now
shows speaker names. Generating suggestions still does *not* publish identities
on its own — the apply step is the editorial gate, and the raw per-segment
candidates stay in the private sidecar.

Open follow-ups: apply labels to **WebVTT** too (currently Podlove/DOTe only,
so caption-based players stay unlabeled); a per-segment review/approval UI
(apply is currently whole-transcript); and deciding the smoothing policy
(carry-forward, the current default, vs. conservative fill only where both
neighbours agree).

8. Operator recipe: diarizing additional episodes via the management command
----------------------------------------------------------------------------

Five further archive episodes were diarized + labelled end to end on production
(2026-05-29) using the known-speaker apply path, all browser-verified
(contributor strip, Podlove player transcript tab, and ``/transcript/`` page):
``das-python-data-model`` (post 131 / audio 73 — hosts only: Jochen, Dominik,
Johannes), ``typescript-und-typisierung`` (post 127 / audio 69 — + guest
**Stefan**), ``freelancing`` (post 128 / audio 70 — Dominik, Jochen + guest
**Birgit**; Johannes absent), ``djangocon-europe-2024`` (post 130 / audio 72 —
Dominik, Jochen + guest **Ronny**; Johannes absent), and ``devops-redux``
(post 129 / audio 71 — Dominik, Jochen + guest **Sujeevan**; Johannes absent).
Per-segment host attribution is voiceprint-based, not order-guessed; guests were
identified from the transcript (Stefan's own book passage; Birgit's freelancer
self-intro; Sujeevan's "… ist mein Name" + GitLab + co-hosting *TILpod* with
Dirk) then seeded as known speakers themselves.

The end-to-end recipe, run as the ``python-podcast`` app user on production:

#. Pick a live episode whose ``podcast_audio`` has no diarized transcript yet and
   enable per-audio diarization (``Audio.transcript_diarization_mode='enabled'``).
#. Assign the candidate contributors (the three hosts, plus any recurring guest
   such as Ronny who already has references) to the **episode** so their approved
   voice references reach Voxhelm.
#. Generate **by episode id**, not audio id (see gotcha below)::

       python manage.py generate_transcripts --episode-id <POST_ID> --force

#. Inspect the private sidecar: ``Transcript.get_speaker_suggestion_summary()``
   lists matched ``known_speakers`` + ``confident_speaker_distribution``. A host
   that does not appear was not in the room — drop their ``EpisodeContributor``.
   The guest is the raw-diarization cluster that is almost entirely *uncertain*
   (matches no host); read its text via ``get_speaker_suggestions()`` +
   ``raw_diarization_speaker`` to confirm identity.
#. Seed the new guest's voiceprint from a clean solo run of that cluster, then
   re-run ``generate_transcripts --episode-id <POST_ID> --force`` so the guest is
   a *known* speaker, and ``Transcript.apply_known_speaker_suggestions()``.
#. Verify: ``/api/audios/podlove/<AUDIO>/post/<POST>/`` returns the mapped
   ``speaker`` labels + ``contributors`` array, then a browser check of the
   contributor strip, the player transcript tab, and the ``/transcript/`` page.

.. important::

   **The management command only sends the known-speaker payload with
   ``--episode-id``.** ``--audio-id`` builds a target with ``episode=None``, and
   ``VoxhelmTranscriptService.submit_for_audio`` skips ``build_known_speaker_references``
   when ``episode is None`` — so an ``--audio-id`` run does plain anonymous
   diarization and stores **no** ``speakers`` sidecar, even with references
   seeded and ``CAST_VOXHELM_KNOWN_SPEAKER_ENABLED=true``.

.. important::

   **Seed each guest as a known speaker before applying.**
   ``apply_known_speaker_suggestions()`` defaults to ``smooth=True``
   (carry-forward), which fills a reference-less guest's uncertain segments with
   the nearest confident *host* — silently mislabelling the whole guest voice.
   Give the guest their own approved reference and re-run KS first (so their
   segments become confident); only then apply. ``smooth=True`` is safe once
   every voice present is a known speaker.
