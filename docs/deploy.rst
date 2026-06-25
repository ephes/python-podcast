Deploy
========

Staging and production deployments run through ops-control (SOPS-backed). The local ``deploy/``
directory is kept as a legacy reference.

Deployment Commands
-------------------

Deploy to staging via ops-control::

    just deploy-staging

Deploy to production via ops-control::

    just deploy-production

The deploy recipes first install/update Ansible collections and the local ``ops-library``
collection via ``uvx ansible-galaxy``. They also install ``community.postgresql`` explicitly
because current ops-control roles require it. The recipes support overriding the launcher
commands when needed::

    ANSIBLE_PLAYBOOK_CMD="uvx --from ansible-core ansible-playbook" just deploy-staging

    ANSIBLE_GALAXY_CMD="uvx --from ansible-core ansible-galaxy" just deploy-staging

Ops-control Prerequisites
-------------------------

* An ops-control clone (set ``OPS_CONTROL`` if not located at ``../ops-control``)
* An ops-library clone (set ``OPS_LIBRARY_PATH`` if not located at ``$PROJECTS_ROOT/ops-library``)
* SOPS age key configured (``SOPS_AGE_KEY_FILE`` defaults to ``~/.config/sops/age/keys.txt``)
* ``PROJECTS_ROOT`` pointing at the parent directory that contains this repo
* ``uv`` installed locally; the just recipes run ``uvx --from ansible-core ansible-playbook``

Transcript Worker
-----------------

Voxhelm transcript generation from Wagtail admin queues completion work on the
``cast_transcripts`` Django Tasks database backend. The ops-control
``deploy-python-podcast.yml`` playbook enables a managed systemd worker in
addition to Gunicorn::

    uv run python manage.py db_worker --backend cast_transcripts --worker-id python-podcast-transcripts

The worker service uses the ``cast_transcripts`` backend alias and the stable
``python-podcast-transcripts`` worker id. The worker requires the
``django_tasks_db`` migrations to have been applied before it starts processing
jobs. Full-episode Voxhelm diarization can exceed django-cast's default polling
window, so this project sets ``CAST_VOXHELM_POLL_TIMEOUT`` to six hours by
default.

Public transcript artifacts
---------------------------

Published transcript artifacts (Podlove/WebVTT/DOTe) are public for this
podcast: podcast feeds link to transcript endpoints and the transcript text is
intended to be available to listeners. django-cast reads raw transcript artifacts
through the ``cast_private_media`` storage alias, so this project points that
alias at the same public S3 media storage as ``default``. This lets django-cast
read the existing S3 objects by their stored names while the public transcript
HTML, player cues, PodcastIndex JSON, and WebVTT remain served through Django.

Private known-speaker suggestion sidecars and contributor voice references are a
separate concern and use the ``cast_voice_references`` filesystem storage under
``private_media/``.

Voxhelm credentials should be supplied through deployment-managed environment
variables rather than relying on the Wagtail database token field. Configure
``CAST_VOXHELM_API_BASE`` and ``CAST_VOXHELM_API_KEY`` in the shared
environment used by both Gunicorn and the transcript worker; the Wagtail
``Voxhelm settings`` token field may stay blank when the token comes from
deployment secrets.

Known-speaker recognition
-------------------------

Anonymous diarization clusters voices but cannot reliably recover a known
recurring speaker on this podcast's mono live-room recordings. To use
contributor voice references for known-speaker recognition:

* Enable diarization (``CAST_VOXHELM_DIARIZATION_ENABLED=true`` or the
  site-level Voxhelm setting).
* Enable known-speaker recognition with ``CAST_VOXHELM_KNOWN_SPEAKER_ENABLED=true``
  (or the site-level Voxhelm setting) in the shared environment used by both
  Gunicorn and the transcript worker.
* Ensure Voxhelm's ``VOXHELM_ALLOWED_URL_HOSTS`` includes the host that serves
  reference audio. References are sent as source ranges into already-uploaded
  mastered audio (the CloudFront media host), so that host must be allowlisted
  on the Voxhelm side.
* Configure the Voxhelm known-speaker backend: ``VOXHELM_DIARIZATION_BACKEND=pyannote``
  with a Hugging Face token (``VOXHELM_HUGGINGFACE_TOKEN``) that has accepted the
  ``pyannote/wespeaker-voxceleb-resnet34-LM`` model terms.

When enabled, diarized transcript jobs send the approved voice references of an
episode's expected contributors to Voxhelm. Voxhelm returns per-segment speaker
suggestions (candidates, confidence, margin, uncertainty, raw diarization
labels) which django-cast stores privately on the transcript. Known-speaker
results are suggestions: public transcript output stays unlabeled until an
editor reviews and approves them.

Applying the django-cast version with these features runs one new migration
(``cast.0071``) adding the private known-speaker suggestion field and the
site-level known-speaker setting. Bump the pinned ``django-cast`` commit, run
``uv lock --upgrade-package django-cast``, apply migrations, and redeploy.
