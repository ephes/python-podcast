API token login throttling
==========================

``POST /api/api-token-auth/`` exchanges a username and password for a
non-expiring Django REST Framework token. The tokens authenticate the
django-cast API through ``rest_framework.authentication.TokenAuthentication``.

Before October 2026 this endpoint had no rate limit, so it could test any
number of password guesses without hitting allauth's login rate limits. It now
uses a throttled view, ``python_podcast.users.api_auth.obtain_auth_token``, with two
limits:

``api_token_auth_client``
    Requests per client address. The default is ``20/hour``. Override it with
    ``DJANGO_API_TOKEN_AUTH_CLIENT_RATE``. The client address is the last
    ``X-Forwarded-For`` entry, which Traefik appends; earlier entries are
    ignored. ``REST_FRAMEWORK["NUM_PROXIES"]`` controls this. It defaults to
    ``1`` and can be changed with ``DJANGO_NUM_PROXIES`` if the proxy chain
    changes.

``api_token_auth_username``
    Requests per submitted username, from any address. The default is
    ``10/hour``. Override it with ``DJANGO_API_TOKEN_AUTH_USERNAME_RATE``.
    Usernames are compared case-insensitively, with surrounding whitespace
    ignored. This limit still holds when a client rotates addresses or sends
    a forged ``X-Forwarded-For`` header.

A ``username`` that is not a string, such as a JSON number, is rejected with
``400`` before authentication. The client limit is checked first. A request
it allows counts towards both limits, successful ones included; a request it
refuses is not counted against the username. A
throttled request gets ``429 Too Many Requests`` with a ``Retry-After``
header, even when the password is correct. The rates live in
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``. No ``DEFAULT_THROTTLE_CLASSES``
is set, so other API views remain unthrottled.

Throttle counters live in the ``api_token_auth_throttle`` cache when it is
configured, and in the ``default`` cache otherwise. Production configures it
as a file-based cache in the ``api-token-auth-throttle`` subdirectory of
``DJANGO_CACHE_LOCATION``, shared by every worker, with ``MAX_ENTRIES`` set to
100000. Page-cache traffic therefore cannot cull the counters, and a client
that is already throttled cannot create new username counters. A per-process
cache such as ``LocMemCache`` would multiply the effective limit by the number
of workers.

Getting a token
---------------

Prefer issuing tokens in the Django admin (*Auth Token* section). Daybook
does this. The endpoint stays available for scripts and notebooks that log in
with a password, such as django-cast's moderation notebooks. Those callers
should fetch a token once and reuse it, since they will hit the limits
otherwise.

Other login surfaces
--------------------

* allauth's ``ACCOUNT_RATE_LIMITS`` defaults apply to ``/accounts/login/``,
  because the project does not override them.
* The Django admin login (``ADMIN_URL``) and the Wagtail admin login
  (``WAGTAILADMIN_BASE_URL``) have no rate limit of their own.

Change history
--------------

* 2026-10: ``api/api-token-auth/`` is throttled per client address and per
  username. Tokens that already exist keep working.
