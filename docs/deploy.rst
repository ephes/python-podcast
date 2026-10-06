Deploy
========

Staging and production deployments run through ops-control (SOPS-backed).

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

Dependency Updates
------------------

``uv.lock`` pins exact versions and Git commits. django-cast tracks ``develop``
and can therefore include unreleased changes. Refresh within the constraints in
``pyproject.toml`` with ``uv lock --upgrade`` and ``uv sync --locked``; use
``uv lock --upgrade-package django-cast`` for a focused Cast update.

Run isolated application and migration checks in Bash or Zsh::

    (
        export DATABASE_URL=sqlite:///:memory:
        export LEGACY_DATABASE_URL=sqlite:///:memory:
        export DJANGO_SETTINGS_MODULE=config.settings.test
        uv run --locked pytest --create-db
        uv run --locked python manage.py makemigrations --check --dry-run
        uv run --locked python manage.py migrate --noinput
    )

Default pytest discovery includes both ``python_podcast`` and ``tests`` and
excludes browser tests through the existing marker setting. Add future test
roots to ``testpaths``. Browser tests need ffmpeg and the browser matching the
locked Playwright version; install it with ``uv run --locked playwright install
chromium`` and run ``just test-e2e``. Before deploying, also check the new frozen
environment with production settings and ``migrate --plan`` against PostgreSQL,
and retain a fresh database backup and the previous commit/lock for rollback.

2026-09-16 django-cast release pin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The focused django-cast refresh advances the intentionally retained Git pin
from ``b36ddd4b`` to the released 0.2.65 commit ``1021142d``. PyPI now also
publishes 0.2.65. No other locked dependency changed. See the
`final release notes <https://github.com/ephes/django-cast/blob/0.2.65/docs/releases/0.2.65.rst>`_.
The 82 application tests and all 11 Chromium browser tests passed on Python
3.14.5. The migration graph applied to empty SQLite, and the settings,
model-change, changed-file hook, and documentation checks also completed.

2026-09-08 refresh
~~~~~~~~~~~~~~~~~~

* django-cast: 0.2.64 at ``c4a9e97a`` to unreleased 0.2.65 at ``b36ddd4b``.
  The latest published PyPI release at upgrade time remains 0.2.64.
* Django: 6.1 to 6.1.1; Wagtail remains 8.0. Both Cast theme pins are unchanged.
* django-indieweb: 0.6.1 to 0.6.2; Gunicorn: 26.0.0 to 26.2.0;
  django-debug-toolbar: 7.0.0 to 8.0.0; Playwright: 1.61.0 to 1.62.0.
* Refreshed 77 packages in total within the existing dependency constraints.
  Removed the now-unused ``setuptools`` and ``decorator`` dependencies;
  ``pkg_resources`` is no longer available in the frozen production environment.

Cast includes permission, feed-isolation, comment, and editor rich-text fixes.
Legacy audio/video collection POST endpoints now reject uploads; clients must
use the editor media API. No project application, configuration, script, or test
references to those legacy upload paths were found. A scan of the shared
production Traefik access log during the companion homepage upgrade found no
such POSTs across 27,632,499 entries; this covers observed usage, not unknown
clients outside the available history. Editor rich-text writes are normalized
against configured Wagtail features. See the
`upstream release notes <https://github.com/ephes/django-cast/blob/b36ddd4b3b3e31b73dd822b749304957c4b3ffe0/docs/releases/0.2.65.rst>`_.

The 82 application tests and all 11 Chromium browser tests passed on Python
3.14.7 using in-memory SQLite. Browser tests used ``config.settings.e2e``,
``DJANGO_ALLOW_ASYNC_UNSAFE=1``, and ``--migrations --create-db`` after installing
the matching Chromium browser. The full migration chain applied to empty SQLite,
and ``makemigrations --check --dry-run`` found no changes. Local settings checks,
including debug-toolbar 8.0, completed with existing allauth deprecation warnings.
The test settings also report a missing Vite manifest.

The new production dependencies, including the pillow-heif wheel, installed in
an isolated environment on the production Linux host with Python 3.14.7.
Against the production PostgreSQL database, that environment's migration plan
was empty and its settings check reported only the allauth deprecations. A fresh
custom-format database dump was saved and its catalog checked with
``pg_restore --list``; the previous dependency files were also retained. No
schema rollback is needed when redeploying the previous commit for this refresh.
PostgreSQL's pre-existing collation-version mismatch was resolved on 2026-09-16
by rebuilding all 114 indexes that use the database default collation
concurrently, then refreshing the database metadata from glibc 2.35 to 2.39.
The post-maintenance check found no invalid user indexes; system catalog indexes
were outside the targeted rebuild. A cluster-wide check found that the
unrelated ``lead`` and ``template1`` databases still carry the old version and
are outside this application release follow-up.

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
intended to be available to listeners. django-cast reads and writes these public
artifacts through the ``cast_public_transcripts`` storage alias, which this
project points at the same public S3 media storage as ``default``. This lets
django-cast read the existing ``cast_transcript/`` S3 objects by their stored
names while the public transcript HTML, player cues, PodcastIndex JSON, and
WebVTT remain served through Django.

Private known-speaker suggestion sidecars and contributor voice references are a
separate concern and use the ``cast_voice_references`` filesystem storage under
``private_media/``. ``cast_private_media`` is not used as the public transcript
workaround anymore.

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
