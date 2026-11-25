Login and password reset rate limits
====================================

The site has three password login forms:

* allauth's ``/accounts/login/``, limited by allauth's default
  ``ACCOUNT_RATE_LIMITS`` (see `allauth limits and the client address`_).
* the Django admin login, ``<ADMIN_URL>login/``.
* the Wagtail admin login, ``<WAGTAILADMIN_BASE_URL>login/`` (``/cms/login/``).

The two admin logins are the plain Django and Wagtail login views without a
rate limit of their own. Editor and admin accounts rely on long, randomly
generated passwords instead. From October 2026 until November 2026 both admin
logins went through a failed-login throttle
(``python_podcast.users.login_throttle``) with its own cache, lock file and
the ``filelock`` dependency; it was removed again because long random
passwords already cover password guessing.

allauth limits and the client address
-------------------------------------

allauth's ``ACCOUNT_RATE_LIMITS`` count per client address as well as per
username or email address: by default ``30/m/ip`` login POSTs, ``10/m/ip``
failed logins plus ``5`` per username in five minutes, and ``20/m/ip`` plus
``5/m`` per address for password reset requests. Every request reaches
gunicorn from Traefik on ``127.0.0.1``, and allauth ignores
``X-Forwarded-For`` unless ``ALLAUTH_TRUSTED_PROXY_COUNT`` is set. Before
November 2026 all visitors therefore shared one address budget: a single
client sending 30 login POSTs a minute locked every editor out of
``/accounts/login/`` and of the password reset.

``config.settings.production`` (and staging, which imports it) now sets
``ALLAUTH_TRUSTED_PROXY_COUNT`` from ``DJANGO_NUM_PROXIES`` (default ``1``),
the same knob as ``REST_FRAMEWORK["NUM_PROXIES"]`` and
``INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS``. allauth then counts the last
``X-Forwarded-For`` entry, which Traefik appends; earlier entries are
client-controlled and ignored. Local and test settings keep allauth's default
``0`` (``REMOTE_ADDR``). If ``DJANGO_NUM_PROXIES`` is ever raised above the
real number of proxies, allauth refuses requests whose ``X-Forwarded-For`` has
fewer entries with ``ImproperlyConfigured``.

Password reset
--------------

Two forms send password reset emails: allauth's
``/accounts/password/reset/`` and Wagtail's
``<WAGTAILADMIN_BASE_URL>password_reset/`` (``/cms/password_reset/``). Before
November 2026 the Wagtail form had no limit, so anyone could send an editor
any number of reset emails through the site's Mailgun account.
``config/urls.py`` now routes the Wagtail form through
``python_podcast.users.password_reset.ThrottledWagtailPasswordResetView``,
which charges allauth's ``reset_password`` rate with the same key (the
lower-cased email address). Both forms share one budget, and a refused
request gets ``429`` without sending an email. Invalid forms and ``GET``
requests are not counted. The rest of Wagtail's reset flow (the emailed link
and the new-password form) is unchanged.

Token authentication
--------------------

``/api/api-token-auth/`` was removed on 2026-10-19 and returns 404. The
``improve_spamfilter`` and ``comments_api_endpoint_debug`` notebooks that
needed token issuance are no longer used.

Existing DRF tokens and ``TokenAuthentication`` remain available: django-cast
API views, including the comments API, inherit the site's
``REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]``. The cast-vue comments
UI uses session authentication and CSRF tokens and needs no token issuance
endpoint.

Change history
--------------

* 2026-10: the Django admin and Wagtail admin logins throttle failed attempts
  per client address and per username.
* 2026-10-19: removed the unused token issuance endpoint.
* 2026-11-06: serialize shared failure histories across web workers.
* 2026-11-17: count allauth rate limits per client address behind Traefik
  (``ALLAUTH_TRUSTED_PROXY_COUNT``), and limit the Wagtail admin password
  reset with allauth's ``reset_password`` rate.

Unreleased
----------

* Remove the admin login throttle, its ``api_token_auth_throttle`` cache,
  ``ADMIN_LOGIN_THROTTLE_LOCK_PATH``, the ``DJANGO_ADMIN_LOGIN_*_RATE``
  settings and the ``filelock`` dependency. The admin logins answer failed
  attempts with the login form again, never ``429``.
