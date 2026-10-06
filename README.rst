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

* To create a **normal user account**, just go to Sign Up and fill out the form. Once you submit it, you'll see a "Verify Your E-mail Address" page. Go to your console to see a simulated email verification message. Copy the link into your browser. Now the user's email should be verified and ready to go.

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

To run the tests, check your test coverage, and generate an HTML coverage report::

    $ coverage run -m pytest
    $ coverage html
    $ open htmlcov/index.html

Running tests with py.test
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

  $ pytest

Continuous Integration
~~~~~~~~~~~~~~~~~~~~~~

GitHub Actions (``.github/workflows/ci.yml``) runs on every push and pull request:

* ``lint``: the pre-commit hooks via ``uv run prek run --all-files``
* ``test``: ``pytest -m "not e2e"`` against a PostgreSQL 17 service container
  (Python 3.14, ``uv sync --locked``), with dummy AWS settings; test settings keep
  uploads in memory. The Playwright e2e tests are not run in CI; use ``just test-e2e``.

Live reloading and Sass CSS compilation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Moved to `Live reloading and SASS compilation`_.

.. _`Live reloading and SASS compilation`: http://cookiecutter-django.readthedocs.io/en/latest/live-reloading-and-sass-compilation.html





Sentry
^^^^^^

Sentry is an error logging aggregator service. You can sign up for a free account at  https://sentry.io/signup/?code=cookiecutter  or download and host it yourself.
The system is setup with reasonable defaults, including 404 logging and integration with the WSGI application.

You must set the DSN url in production.


Deployment
----------

Production deployments run via ops-control (SOPS-backed). Use ``just deploy-production``.
The just deploy recipes bootstrap Ansible collections via ``uvx`` before running the
ops-control playbook.



Docker
^^^^^^

See detailed `cookiecutter-django Docker documentation`_.

.. _`cookiecutter-django Docker documentation`: http://cookiecutter-django.readthedocs.io/en/latest/deployment-with-docker.html
