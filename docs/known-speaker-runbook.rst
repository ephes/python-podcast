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

8. Parakeet re-run of all episodes (2026-10-19/20)
---------------------------------------------------

All 68 published episodes now have Voxhelm transcripts from Parakeet
(``parakeet-tdt-0.6b-v3``), with names applied through
``apply_known_speaker_suggestions(smooth=False)``. Only confident segments
carry a name, and uncertain ones stay empty. The unpublished pp_16 was left
out on purpose.

How it ran:

* No ``generate_transcripts``: it works serially and does not apply
  ``smooth=False``. A batch script instead submitted all jobs of a batch at
  once with ``VoxhelmTranscriptService.submit_for_audio`` (fresh task ref
  ``cast-audio-<id>-parakeet-bulk-20261019``; an old ref would return the old
  whisper.cpp job), then imported each episode separately with
  ``complete_audio_job`` and applied the names right after.
* Before every import there was a backup of all transcript files (podlove,
  vtt, dote, speakers, corrections) with SHA-256, the row and the speaker
  mappings. The import refused if the files had changed since the backup, if
  the job was not ``parakeet``, or if the speakers artifact was missing.
  ``complete_audio_job`` deletes the old files after commit.
* Order: first 8 finished pilot jobs (no GPU), then a canary with the largest
  MP3 (pp05, 160 MB) and pp04, then batches of 10. Stop rules: more than 15 %
  unnamed, a name outside the episode's contributors, under 80 % right or
  more than 3 % wrong passages against the stems. No stop was needed.
* Staging is no help for this: it writes to the same S3 bucket, and a re-run
  there deletes production's files.

Results against per-speaker stems (28 episodes whose master is exactly as long
as the stems; 100 ms frames):

* right: median 88.0 % → **92.2 %**. 27 of 28 better. pp_50 is marginally
  worse (92.8 → 91.9 %).
* wrong passage (more than 1 s away from a speaker change): median 0.8 % →
  0.0 %, at most 0.3 %.
* unnamed: median 1.6 %, at most 11.4 % (in-room episodes with crosstalk on
  Johannes's mic, such as pp_27).
* Readability: lines without capitals or final punctuation are down from about
  60 % to 3 %.

New voice references: Dodo and Niklas (pp04, references 35–38). Who was who
came from their self-introductions in the transcript. Unnamed share in pp04:
71 % → 10.5 %.

Things worth a listen: pp05 (Jochen at 91 %, the old version had the same
split), pp_27 at 107:20 and pp_28 at 5:39 (crosstalk). The run record with
per-episode numbers and backups is in Voxhelm under
``var/handoff/2026-10-19_python_podcast_parakeet_bulk/`` (local, not in the
repo).

Remaining follow-up
-------------------

The Wagtail review-and-apply path has landed: an editor reviews the private
suggestions and applies the approved labels to public Podlove/DOTe via
``Transcript.apply_known_speaker_suggestions()``. This was exercised on
production for ``pp_62`` (episode 135), so that episode's public transcript now
shows speaker names. Generating suggestions still does *not* publish identities
on its own — the apply step is the editorial gate, and the raw per-segment
candidates stay in the private sidecar.

Open follow-ups: a per-segment review/approval UI (apply is currently
whole-transcript). Done since: ``apply_known_speaker_suggestions()`` also labels
WebVTT, and the public smoothing policy for python-podcast is ``smooth=False``
(decided 2026-10-19, see step 8).
