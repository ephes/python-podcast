Python Podcast
==============

Personal Python Podcast Site

.. image:: https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg
     :target: https://github.com/pydanny/cookiecutter-django/
     :alt: Built with Cookiecutter Django


:License: BSD


Settings
--------

Moved to settings_.

.. _settings: http://cookiecutter-django.readthedocs.io/en/latest/settings.html

Basic Commands
--------------

Setting Up Your Users
^^^^^^^^^^^^^^^^^^^^^

* Registration is closed by default. To enable Sign Up for local development,
  set ``DJANGO_ACCOUNT_ALLOW_REGISTRATION=true`` in your environment or local
  ``.env`` file, then restart Django. Leave it unset or set it to ``false`` to
  keep registration closed.

* Both local and social-account signup obey this setting; closing registration
  still permits existing accounts to log in. Run the synthetic admission tests
  with ``uv run --locked pytest python_podcast/users/tests/test_signup_admission.py``.
  They exercise real allauth routes with a local dummy provider, without OAuth
  network calls, and verify that refused requests create no account/email rows.

* When registration is enabled, go to Sign Up to create a **normal user account**.
  After submitting the form, follow the verification link printed in the local
  development console to verify the email address.

* To create an **superuser account**, use this command::

    $ python manage.py createsuperuser

* User pages under ``/users/`` are not a public member directory. The list at
  ``/users/`` is for staff only: anonymous visitors are sent to the login page and
  logged-in non-staff users get a 403. A profile at ``/users/<username>/`` is shown
  to its owner and to staff; anyone else gets a 404, so the page does not reveal
  whether a username exists.

For convenience, you can keep your normal user logged in on Chrome and your superuser logged in on Firefox (or similar), so that you can see how the site behaves for both kinds of users.

Type checks
^^^^^^^^^^^

Running type checks with mypy:

::

  $ mypy python_podcast

Test coverage
^^^^^^^^^^^^^

Install the locked development dependencies with ``uv sync --locked`` first.
They include ``django-coverage-plugin``, which ``.coveragerc`` loads and which
``python commands.py coverage`` requires. Template coverage additionally needs
template debugging enabled and a coverage core that supports plugin file tracers
(such as ``COVERAGE_CORE=ctrace``). The default SysMonitor core on Python 3.14 and
later does not support plugin file tracers, so installing the plugin alone does not enable
template coverage.

To run the tests, check your test coverage, and generate an HTML coverage report::

    $ coverage run -m pytest
    $ coverage html
    $ open htmlcov/index.html

Running tests with py.test
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

  $ pytest

Local quality commands
~~~~~~~~~~~~~~~~~~~~~~

With the development environment active, ``python commands.py mypy``,
``python commands.py test`` and ``python commands.py coverage`` return a
nonzero exit status when a tool fails (preserving its exit code), or status 1
with an error message when a tool cannot start. Their existing tool arguments
and test environment remain unchanged; mypy must be installed separately.
Coverage stops at the first failed step: failed tests do not generate or open
an HTML report, and failed HTML generation does not open a stale report.
On macOS and supported WSL kernels, opening the generated report is best effort:
an unavailable viewer or nonzero viewer status prints a message and leaves
successful coverage generation successful.

Continuous Integration
~~~~~~~~~~~~~~~~~~~~~~

GitHub Actions (``.github/workflows/ci.yml``) runs on every push and pull request:

* ``lint``: the pre-commit hooks via ``uv run prek run --all-files`` (Python 3.15)
* ``test``: ``pytest -m "not e2e"`` against a PostgreSQL 17 service container
  (Python 3.14 and 3.15, uv 0.13, ``uv sync --locked``), with dummy AWS settings; test settings keep
  uploads in memory.
* ``dock-transitions``: isolated Playwright tests of deferred dock updates in
  Chromium, plus enhanced-navigation redirects and deadlines, for source and
  minified JS, without Django or a database. Other
  Playwright e2e tests run locally with ``just test-e2e``.

Before pushing playback changes, run ``just test-core-media`` locally. This
five-minute gate explicitly selects the real custom-player and persistent
playback/transcript cases in Chromium with ``config.settings.e2e`` and dependency
migrations. It requires PostgreSQL, ffmpeg/ffprobe and installed Chromium
(``uv run --locked playwright install chromium``), plus the Vite manifests shipped
in the locked packages. Set ``DATABASE_URL`` to a disposable local database and
the dummy AWS settings listed in ``.github/workflows/ci.yml``; no real accounts
or media are used. All audio/transcript storage is local to fixture temporary
directories; the existing WhiteNoise dependency serves byte ranges from those
directories so Chromium can seek. External browser requests (analytics) receive
empty responses.
The gate checks the exact seven JUnit testcase identities (browser, theme and
response-order parameters), rejecting duplicates, substitutions and skips.
It supports POSIX process groups on Linux/macOS; timeout or Ctrl-C terminates the
owned pytest/browser/server group with bounded TERM/KILL escalation. Descendants
that deliberately detach into another session are outside that guarantee.
See ``docs/enhanced_navigation.rst`` for maintaining the case contract and running
the platform-independent harness tests.
Missing assets, broken media routing, failed playback or a deadline overrun fail
the command. This gate runs locally; no additional Actions job is configured.
See ``docs/enhanced_navigation.rst`` for the strict transcript-fetch oracle.

Dependency security updates (Unreleased)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The lockfile updates Tornado from 6.5.10 to 6.6 for folded-header and chunked-body
denial of service (GHSA-pcg2-g6cj-q92c, GHSA-r4j5-9xpp-3985) and unsafe
capture-based redirects (GHSA-pw9p-v7r6-gx4p). Tornado is pulled in by the
development notebook stack. Synthetic regressions cover folded-header rejection
and redirect host protection without timing assertions or external services.

Black is updated from 26.5.1 to 26.10.1 in the lockfile; its pre-commit hook is
aligned to 26.10.1. GHSA-cg8m-r9f2-5wm2 affects Black's GitHub Action with
``use_pyproject: true``, which this repository does not use.

Live reloading and Sass CSS compilation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Moved to `Live reloading and SASS compilation`_.

.. _`Live reloading and SASS compilation`: http://cookiecutter-django.readthedocs.io/en/latest/live-reloading-and-sass-compilation.html





Sentry
^^^^^^

Sentry is an error logging aggregator service. You can sign up for a free account at  https://sentry.io/signup/?code=cookiecutter  or download and host it yourself.
The system is setup with reasonable defaults, including 404 logging and integration with the WSGI application.

You must set the DSN url in production.

Visitor IPs, user identities, cookies and request bodies are not sent to Sentry;
see ``docs/deploy.rst`` (Sentry Privacy).


Deployment
----------

Production deployments run via ops-control (SOPS-backed). Use ``just deploy-production``.
The just deploy recipes call ops-control's ``deploy-one`` dispatcher, which
selects the engine and safety guards per host. ``just deploy-bootstrap`` is a
manual setup step only for legacy Ansible targets; pyinfra does not need it.
See ``docs/deploy.rst`` for source selection and prerequisites.



Docker
^^^^^^

See detailed `cookiecutter-django Docker documentation`_.

.. _`cookiecutter-django Docker documentation`: http://cookiecutter-django.readthedocs.io/en/latest/deployment-with-docker.html

Webmentions
-----------

Public cast pages advertise ``/indieweb/webmention/`` via an HTTP Link header.
Received mentions are queued on the existing ``cast_transcripts`` database
worker and verified in the background. They are available for owner inspection
in Django admin under Indieweb → Webmentions; none are rendered publicly,
including verified mentions. Verification status is not approval. IndieAuth,
Micropub and token endpoints remain unavailable. See ``docs/deploy.rst``
(Receiving webmentions) for rate limits, migrations and worker operations.
