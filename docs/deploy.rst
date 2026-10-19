Deploy
========

Staging and production deployments run through ops-control (SOPS-backed).

Registration
------------

Registration is closed by default in all environments. Set
``DJANGO_ACCOUNT_ALLOW_REGISTRATION=true`` in the deployment environment only
when public signup is intended. An unset value or ``false`` keeps signup closed.

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

    ANSIBLE_PLAYBOOK_CMD="uvx --python 3.14 --from ansible-core ansible-playbook" just deploy-staging

    ANSIBLE_GALAXY_CMD="uvx --python 3.14 --from ansible-core ansible-galaxy" just deploy-staging

Ops-control Prerequisites
-------------------------

* An ops-control clone (set ``OPS_CONTROL`` if not located at ``../ops-control``)
* An ops-library clone (set ``OPS_LIBRARY_PATH`` if not located at ``$PROJECTS_ROOT/ops-library``)
* SOPS age key configured (``SOPS_AGE_KEY_FILE`` defaults to ``~/.config/sops/age/keys.txt``)
* ``PROJECTS_ROOT`` pointing at the parent directory that contains this repo
* ``uv`` installed locally; the just recipes run ``uvx --python 3.14 --from ansible-core ansible-playbook``.
  Ansible is pinned to Python 3.14 because ansible-core 2.21 does not start on Python 3.15.

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

2026-10-17 django-cast develop refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` advances only django-cast from ``704a60aa`` to ``ddcc44d9``
(0.2.68 development). It adds transcript glossary snippets, private correction
sidecars and editor review, preserves approved speaker mappings when transcript
text changes, and omits the speaker-count hint for known-speaker Voxhelm jobs.

Deploy with migrations ``cast.0084`` through ``0086``. Migration ``0084`` reads
existing stored transcript files to backfill source fingerprints; retain a fresh
database backup before deployment. The corrections sidecar uses the private
voice-reference storage backend. Existing transcripts are not automatically
glossary-corrected by the migrations; corrections run on future Voxhelm imports
or through ``apply_transcript_glossary``. Rolling code back does not undo
transcript edits or remove the added schema.

Validation: 360 application tests passed on PostgreSQL 17 with ``--migrations``
(49 browser tests deselected), all prek hooks passed, and
``makemigrations --check --dry-run`` found no changes. An isolated Python 3.15
production environment passed system checks with the existing allauth
deprecation warnings and showed only the three expected pending Cast migrations.

The refresh was deployed on 2026-10-17 from a working tree without committing
the lock. The production deploy of ``8aaa4dd`` on 2026-10-19 therefore
installed ``704a60aa`` again. The migrations stayed applied, the code did not
match them, and transcript corrections and source fingerprints were missing.
This commit records the lock and was deployed the same day. **Deploy only from
a commit that contains the lock you mean to ship.**

2026-10-15 Python 3.15
~~~~~~~~~~~~~~~~~~~~~~

Production moves from Python 3.14.8 to 3.15.0. The interpreter is set in
ops-control (``wagtail_python_version`` in
``playbooks/deploy-python-podcast.yml``); the ops-library ``wagtail_deploy``
role installs it with uv, rebuilds the virtualenv when the version differs and
runs ``uv sync --frozen``. Expect a short outage while the virtualenv is
rebuilt.

* ``uv.lock`` moves pydantic to 2.14.1, pydantic-core to 2.50.1, markupsafe to
  3.0.4, rcssmin and rjsmin to 1.3.0, which ship Python 3.15 wheels, and
  django-indieweb ``develop`` from ``dc6365af`` to ``c1918dc6``. No migration.
* The django-indieweb update limits request bodies on the IndieAuth
  authorization and token endpoints. This site routes only the Webmention
  endpoint and its status URL, so nothing changes here.
* PyYAML (a development dependency through Jupyter) has no 3.15 wheel yet and
  is built from source during ``uv sync`` on the host; the host has a C
  compiler.
* CI tests on Python 3.14 and 3.15 with uv 0.13.1 (3.15.0 needs uv 0.13.0 or
  later); lint and the dock transition browser tests run on 3.15.
* Django 6.1 and Wagtail 8.0 do not list Python 3.15 as supported yet. The
  tests pass on 3.14.8 and 3.15.0 against PostgreSQL 17 (38 with
  ``--migrations``, then 355 passed and 1 skipped), as do the 12 dock
  transition browser tests on 3.15.0.

Rollback: set ``wagtail_python_version`` back to ``"3.14.8"`` in ops-control
and deploy again; the role rebuilds the virtualenv on 3.14. The lock works on
both versions.

2026-10-14 library refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-cast ``develop`` from ``5ac84fbd`` to ``704a60aa``,
django-indieweb ``develop`` from ``9726be2d`` to ``dc6365af`` and
cast-bootstrap5 ``main`` from ``88134d96`` to ``9fba4b2d``. No other locked
package changed. None of the updates has a migration or needs a settings change.

* django-cast writes internal page links in feed item descriptions as absolute
  URLs, so they resolve in podcast apps and feed readers. Voxhelm status polls
  retry lost connections until the job deadline instead of failing the job.
  Applying speaker suggestions names a guest without a voice reference from the
  leftover diarization label when the assignment is unambiguous.
  ``media_stale`` now skips files younger than 7 days
  (``CAST_MEDIA_STALE_MIN_AGE_DAYS``) or of unknown age and re-checks age and
  references before each deletion. Nothing here runs it on a schedule.
* django-indieweb falls back to ``GET`` when outbound Webmention discovery gets
  an error answer to ``HEAD``. Its other behaviour changes (``create`` scope
  for multipart Micropub, ``404`` for rejected WebSub callbacks, fail-closed
  ``INDIEWEB_LOG_REDACTION``) concern views this site does not route and a
  setting it does not set.
* cast-bootstrap5 ships a compiled German catalog, so its theme strings appear
  in German here (``LANGUAGE_CODE`` is ``de-DE``), and sets ``<html lang>`` from
  the active language. This site's ``cast/bootstrap5/base.html`` extends the
  theme's template, so its pages now declare German instead of ``en``.

2026-10-13 library refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-indieweb ``develop`` from ``c7b8da62`` to ``4022366f``,
django-cast ``develop`` from ``8205bc48`` to ``5ac84fbd`` (0.2.68 development),
cast-bootstrap5 ``main`` from ``d0ea6879`` to ``88134d96``.
No other locked package changed. None of the updates has a migration.

One setting is new: ``config.settings.production`` sets
``INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS`` from ``DJANGO_NUM_PROXIES`` (default
``1``), so django-indieweb rate limits count the client address that Traefik
appends to ``X-Forwarded-For`` and not Traefik's own address. Local and test
settings keep the library default ``0`` (``REMOTE_ADDR``).

**Check before deploying:** django-cast now takes the Voxhelm API base and
token as a pair from one level: the Wagtail ``Voxhelm settings`` of the site
if either field is filled, otherwise the Django settings, otherwise the
environment. A site that has only one of the two Wagtail fields filled no
longer inherits the other from the environment, and transcript generation is
disabled for it. Before the deploy, open ``Settings -> Voxhelm settings`` for
every site and make sure that either both fields are blank (deployment
credentials are used) or both are filled. Changing the API base in Wagtail now
requires re-entering the token; saving with both fields blank removes the
stored token.

* django-indieweb analyses at most two received Webmention documents at a
  time per lock directory (``INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT``). A
  further one waits up to 1 s for a slot; after that a synchronous receive
  answers ``503`` with ``Retry-After: 1``. An already verified mention keeps
  its state; a new submission is left as a ``pending`` row. Fetching a
  source or Vouch document has a total budget of 15 s
  (``INDIEWEB_WEBMENTION_FETCH_TOTAL_TIMEOUT_SECONDS``); a source that sends
  its body too slowly is marked ``failed``. Relative links in a source are
  resolved against the fetched source URL, so posts on this site can mention
  each other with relative links; documents containing ``<base`` still match
  on absolute links only. All new settings stay at their defaults.
  When this was written the project did not route any django-indieweb URL.
  The receiving endpoint is routed since; see `Receiving webmentions`_.
* django-indieweb keeps the complete ``next`` URL, including the
  authorization parameters, when IndieAuth or token management redirects to
  the login page.
* A follow-up on the same day moves django-indieweb ``develop`` from
  ``4022366f`` to ``9726be2d``; no other locked package changed and there is
  no migration or settings change. Its endpoint rate limit now stores the
  count and the window deadline together, so the configured window is fixed
  from a client's first request and no longer extends while the client keeps
  sending on a file-based cache; ``Retry-After`` is the time left to that
  deadline. Counting stays best-effort under simultaneous requests. The
  counters use a new cache key namespace, so every client starts with a
  fresh allowance after the upgrade. When this was written no
  ``INDIEWEB_RATE_LIMITS`` were configured and no django-indieweb URL was
  routed; both changed with `Receiving webmentions`_.
* django-cast leaves view-restricted pages, and pages below them, out of the
  navigation links of blog, post and feed pages, for signed-in visitors too.
  Feed descriptions are rendered with the default theme of the blog or site
  and ignore a visitor's session, query or preview theme.
* django-cast answers HTMX theme-selector requests with the plain fragment
  when a theme has no ``select_theme.html``, and ``manage.py check`` reports
  missing optional theme templates as ``cast.W002`` warnings.
  ``Transcript.rewrite_speaker_labels`` also renames generic ``Speaker N:``
  cue prefixes.
* cast-bootstrap5 ships rebuilt bundles, so ``collectstatic`` picks up new
  hashed assets. A Podlove player that fails to load shows a message and a
  ``Retry loading player`` button instead of loading forever. The color mode
  choice applies for the rest of the page session when the browser refuses to
  store it. Search suggestions give up after 5 s and say so; submitting the
  search still works. Consecutive plain blockquotes merge only when nothing
  but whitespace separates them and they carry no attributes such as ``cite``
  or ``id``.

2026-10-12 security library refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-indieweb ``develop`` from ``289ea25a`` to ``c7b8da62``,
django-cast ``develop`` from ``95965b91`` to ``8205bc48`` (0.2.68 development),
cast-bootstrap5 ``main`` from ``4ed370aa`` to ``d0ea6879`` and cast-vue ``main``
from ``a0db14fb`` to ``0e1d408b``. No other locked package changed. None of the
updates has a migration, and no settings change is needed.

* django-indieweb parses fetched Webmention source and Vouch documents in a
  short-lived child process, ``python -m indieweb.webmention_parse_worker``,
  one per fetched document. The child limits itself to 512 MiB of address
  space and 20 s of CPU time; the receiving process ends it after 30 s. Over a
  limit the Webmention is marked ``failed`` and nothing from the document is
  stored. The ``INDIEWEB_WEBMENTION_PARSE_*`` settings stay at these defaults.
  When this was written no Webmention endpoint was exposed. It is now (see
  `Receiving webmentions`_), and the child process is started by the
  ``cast_transcripts`` database worker, not by gunicorn. The ``wagtail_deploy`` units
  (``NoNewPrivileges``, ``PrivateTmp``, ``ProtectSystem=strict``) have no
  system call filter, memory limit or task limit that would stop the child or
  its ``setrlimit`` calls, and gunicorn runs from the same virtualenv.
* django-cast limits comment posting to ``CAST_COMMENTS_POST_RATE_LIMIT`` posts
  (default 20) per ``CAST_COMMENTS_POST_RATE_WINDOW`` seconds (default 600) per
  logged-in user or anonymous client address and answers further posts with
  ``429`` and ``Retry-After``. Both settings stay at their defaults. The
  client address comes from ``REST_FRAMEWORK["NUM_PROXIES"]``
  (``DJANGO_NUM_PROXIES``, default ``1``), which matches Traefik as the only
  reverse proxy; see :doc:`admin_login_throttle`. The counters live in the
  ``default`` cache, not in ``api_token_auth_throttle``.
  The production ``default`` cache is a file cache with Django's default
  ``MAX_ENTRIES`` of 300. When it is full, culling removes entries at random,
  which can drop a counter and reset that client's budget early.
* django-cast ``media_replace --yes`` and ``recalc_video_posters`` now exit
  non-zero when at least one item failed, and ``media_backup`` has a new
  ``--refresh-changed`` option. No deploy step or scheduled job here runs these
  commands.
* cast-bootstrap5 and cast-vue ship rebuilt bundles (gallery metadata and modal
  focus fixes; comment drafts and list state fixes), so ``collectstatic`` picks
  up new hashed assets.

The 269 application tests passed on Python 3.14.8 against PostgreSQL; browser
tests were not run. ``makemigrations
--check`` reported no changes.

2026-10-12 cast-bootstrap5 refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-bootstrap5 ``main`` from ``bcd0b513`` to ``4ed370aa``. No
other locked package changed. The source conflict that kept it at ``bcd0b513``
(see the refresh note below) is resolved: cast-bootstrap5 ``main`` now takes
django-cast from the ``develop`` branch, as this project does.

The update brings the search suggestion input fixes (text composition and
modified clicks are respected) with a rebuilt search modal bundle, so
``collectstatic`` picks up a new hashed asset. It has no migrations and needs no
settings change.

2026-10-12 django-cast and django-indieweb refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-cast ``develop`` from ``0e55a47b`` to ``95965b91`` and
django-indieweb ``develop`` from ``5187311d`` to ``289ea25a``. No other locked
package changed. cast-bootstrap5 stays at ``bcd0b513``: its ``main`` now pins
django-cast to a fixed commit in ``tool.uv.sources``, which conflicts with
tracking ``develop`` here.

* django-indieweb migration ``0029_reconcile_no_scope_grants`` deletes duplicate
  no-scope tokens and auth codes before ``0030_scope_not_null`` makes the scope
  column non-null. Take a database backup before deploying.
  The ops-control deploy migrates while the previous release is still serving
  and restarts the service afterwards. The previous pin stores a no-scope grant
  as ``NULL``, so an IndieAuth authorization issued without a scope during that
  window can recreate a duplicate and make ``0030`` fail, or fail itself once
  ``0030`` has run. Do not authorize IndieAuth clients while deploying. If
  ``0030`` fails, ``0029`` is already recorded and a plain rerun skips it:
  run ``migrate indieweb 0028`` (reversing ``0029`` is a no-op), then deploy
  again so ``0029`` reconciles the new rows before ``0030``.
* django-cast strips EXIF GPS from new image uploads. Existing originals are not
  rewritten; ``python manage.py report_image_gps`` lists them read-only.
* django-cast restricts the Wagtail images API to staff unless
  ``CAST_PUBLIC_IMAGES_API`` is ``True``. The setting stays unset here.

The 153 application tests passed on Python 3.14.7 against PostgreSQL; browser
tests were not run. ``makemigrations --check`` reported no changes.

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

.. _sentry-privacy:

Sentry Privacy
--------------

Error reports sent to Sentry do not identify visitors or users:
``config.settings.production`` calls ``sentry_sdk.init`` with
``send_default_pii=False`` and ``max_request_body_size="never"``. Events keep
the stack trace (including local variables) and the request URL, method and
non-sensitive headers, but not client IP addresses, the logged-in user,
cookies or request bodies (form posts, JSON payloads, uploads).

These are fixed defaults, not ``.env`` settings; change them in the settings
module only after an owner decision. ``tests/test_production_sentry.py``
guards them.

.. _hsts:

HSTS
----

Two layers send ``Strict-Transport-Security``:

* Traefik, through the ``wagtail_deploy`` headers middleware in ops-library:
  ``stsSeconds: 15552000`` (180 days), ``stsIncludeSubdomains`` and
  ``stsPreload``. This is the header visitors see while that middleware is in
  place.
* Django's ``SecurityMiddleware`` (``config.settings.production``), as the
  fallback when the site is served without that middleware.

Django defaults to the same 180 days with ``includeSubDomains`` and **without**
``preload``. The old cookiecutter value (``max-age=60`` plus ``preload``) is
gone. ``preload`` asks browsers to hard-code the domain and its subdomains as
HTTPS-only; removal from the preload list takes months, and hstspreload.org
requires ``max-age`` of at least one year anyway, so the token does nothing
useful at 180 days. ``manage.py check --deploy`` reports ``security.W021``
for this on purpose.

The settings can be overridden from ``.env``:

* ``DJANGO_SECURE_HSTS_SECONDS`` (default ``15552000``)
* ``DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`` (default ``True``)
* ``DJANGO_SECURE_HSTS_PRELOAD`` (default ``False``)

Upgrade path to preload (owner decision): confirm every subdomain of the domain
serves HTTPS, set ``DJANGO_SECURE_HSTS_SECONDS=31536000`` and
``DJANGO_SECURE_HSTS_PRELOAD=True``, raise ``stsSeconds`` in the Traefik
middleware to match, then submit the domain at https://hstspreload.org/.
Until then the ``stsPreload`` flag in the Traefik middleware should be dropped
in ops-library so both layers agree.

2026-10-09 database connection recovery
----------------------------------------

Production and staging enable ``CONN_HEALTH_CHECKS`` on the default database.
Django checks persistent connections before reuse during a request and replaces
connections closed by a PostgreSQL restart. The existing 60-second
``CONN_MAX_AGE`` remains unchanged. Requests made while PostgreSQL is unavailable
can still fail; this setting does not retry interrupted transactions.

The verified recovery path is persistent connection reuse by web requests;
this is not a retry mechanism for interrupted transcript tasks. The transcript
worker retains systemd's automatic restart on unexpected database connection
failures. For planned PostgreSQL maintenance, pause task producers, drain both
``READY`` and ``RUNNING`` tasks, and gracefully stop active database task workers.
Verify clean shutdown and re-check queue state before restarting PostgreSQL;
restore workers and producers after database readiness. The current worker stop
timeout is 90 seconds, so a long task must finish before maintenance. PostgreSQL
is shared with other applications; coordinate their workers and maintenance
window too.
The operator procedure and staging verification are recorded in ops-control's
``runbooks/python-podcast-database-maintenance.md``.

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
environment used by both Gunicorn and the transcript worker, and leave both
the API base and the token field of the Wagtail ``Voxhelm settings`` blank.
django-cast takes the two values as a pair from one level: a site with only
one of the two Wagtail fields filled does not inherit the other from the
environment, and transcript generation is disabled for it.

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

Receiving webmentions
---------------------

Only two django-indieweb views are routed (pinned at develop ``dc6365a``),
both without authentication:

* ``/indieweb/webmention/`` accepts ``POST`` (submit a mention), ``GET`` and
  ``HEAD`` (a plain-text discovery response with the ``Link`` header) and
  ``OPTIONS`` (CORS preflight). Other methods get ``405``.
* ``/indieweb/webmention/<status_token>/`` accepts ``GET``, ``HEAD`` and
  ``OPTIONS``. GET and HEAD use the status polling rate limit described below.
  A status token is an unguessable random value known only from the
  ``Location`` header of the submission.

IndieAuth, authorization metadata, token issuance,
introspection, token management/revocation, Micropub, media and WebSub callbacks
remain unrouted (404). The status URL returns verification state and, when
available, its timestamp; it does not disclose submitted URLs or content.

Live, public cast blog, post and episode pages advertise the endpoint through
an HTTP ``Link: <…/indieweb/webmention/>; rel="webmention"`` header, across all
themes. Drafts, previews, restricted pages (including ancestor restrictions),
account/admin pages and error responses do not advertise it. The receiver
accepts HTTP(S) targets on the current Django Sites domain; discovery is limited
to public cast content. No custom target resolver or comment adapter is enabled.

A submission stores a ``pending`` Webmention, enqueues
``python_podcast.core.webmention_tasks.process_webmention`` on the
``cast_transcripts`` Django Tasks database backend and returns ``202 Accepted``
with its status URL in ``Location``. The request does not fetch remote pages.
The existing ``python-podcast-db-worker`` verifies the source backlink and
stores parsed data. It shares the transcript queue: long transcript jobs can
delay verification for hours. With no worker, mentions stay pending. Locally,
run ``uv run python manage.py db_worker --backend cast_transcripts``; test
settings use ImmediateBackend and intentionally execute tasks immediately.

A missing backlink or failed fetch marks the mention ``failed``. A failed task
appears under Tasks Database Backend in Django admin, can leave the mention
``pending``, and is not retried automatically. Re-submitting the source/target
pair queues it again.

``INDIEWEB_RATE_LIMITS`` permits 60 receiving requests per client address and
HTTP method in a fixed 300-second window; excess requests get ``429`` with
``Retry-After`` and enqueue nothing. Production's existing
``INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS`` selects the address appended by
Traefik. Counters use the shared default file cache: increments are not atomic
and cache eviction can reset them early. A cache write failure rejects requests.

Status polling at ``/indieweb/webmention/<status_token>/`` uses the
``webmention_status`` limit: 120 requests per client address and HTTP method
(GET and HEAD separately) per 300 seconds; excess requests get ``429`` with
``Retry-After``. The same shared file cache and counter caveats described
above apply to status polling.

Owner inspection and publication
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Received mentions are visible to authorized staff in Django admin under
**Indieweb → Webmentions**, with source/target, author, content and status.
The library stores ``pending``, ``verified``, ``failed`` and ``spam``: these
are processing states, not owner approval. Homepage renders verified mentions
using its template tags; it has no separate approval status. Python Podcast
renders none of them on public pages, including verified mentions, and does
not convert them into public comments. Owner inspection is required before
any future publication workflow; changing status in admin does not publish.

No project migration is needed: ``indieweb`` is already installed and its
packaged migrations own these tables. Normal deployment must run ``uv run
python manage.py migrate`` before starting web/worker processes; verify with
``uv run python manage.py showmigrations indieweb``. CI additionally runs the
Webmention tests with real migrations and checks their applied history and
Webmention table, since the regular suite uses ``--no-migrations``.
