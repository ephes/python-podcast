Admin login throttling
======================

The site has three password login forms:

* allauth's ``/accounts/login/``, limited by allauth's default
  ``ACCOUNT_RATE_LIMITS``.
* the Django admin login, ``<ADMIN_URL>login/``.
* the Wagtail admin login, ``<WAGTAILADMIN_BASE_URL>login/`` (``/cms/login/``).

Before October 2026 the two admin logins were plain Django ``LoginView``\ s
with no rate limit, so they accepted any number of password guesses.
``config/urls.py`` now routes both through
``python_podcast.users.login_throttle.throttle_failed_logins``, which limits
**failed** login attempts:

``admin_login_client``
    Failed attempts per client address. The default is ``20/hour``. Override
    it with ``DJANGO_ADMIN_LOGIN_CLIENT_RATE``. As for
    ``api/api-token-auth/``, the client address is the last
    ``X-Forwarded-For`` entry, which Traefik appends; earlier entries are
    ignored. ``REST_FRAMEWORK["NUM_PROXIES"]`` (``DJANGO_NUM_PROXIES``,
    default ``1``) controls this.

``admin_login_username``
    Failed attempts per submitted username, from any address. The default is
    ``10/hour``. Override it with ``DJANGO_ADMIN_LOGIN_USERNAME_RATE``.
    Usernames are compared case-insensitively after the same NFKC
    normalization the login form applies, with surrounding whitespace ignored. This limit still holds when a client rotates addresses or sends a
    forged ``X-Forwarded-For`` header.

Both admin logins share the same counters. A POST counts as failed unless it
logs a user in, so a wrong password and an invalid form count. The Django
admin form refuses valid credentials of an account without staff status, so
those count as failed there. The Wagtail login logs such a user in, so there
they count as a successful login. Wagtail then admits only users with the
``wagtailadmin.access_admin`` permission, independently of staff status.
Successful logins do not count. GET requests are never throttled.

The client limit is checked first, and a refused request is not counted
against anything. Once either limit is reached, every POST is refused with
``429 Too Many Requests`` and a ``Retry-After`` header, even with the correct
password, until the oldest counted failure is older than the window.

The rates live in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` next to the
token login rates. The counters use the same cache as the token login
throttle: the ``api_token_auth_throttle`` cache when it is configured
(production: a shared file-based cache under ``DJANGO_CACHE_LOCATION``), and
the ``default`` cache otherwise. See :doc:`api_token_auth`.

Locked out?
-----------

Anyone who knows a username can use up its ``admin_login_username`` budget
and lock the admin logins for that user for up to an hour. To get in anyway:

* log in at ``/accounts/login/`` instead. That session also opens the Django
  admin and the Wagtail admin, or
* clear the counters, for example with
  ``python manage.py shell -c "from django.core.cache import caches; caches['api_token_auth_throttle'].clear()"``
  on the server (this also clears the token login counters).

Change history
--------------

* 2026-10: the Django admin and Wagtail admin logins throttle failed attempts
  per client address and per username.
