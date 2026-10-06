"""Throttled replacement for DRF's ``obtain_auth_token`` view.

``POST /api/api-token-auth/`` exchanges a username and password for a
non-expiring DRF token. Without throttling it is an unlimited password oracle
that bypasses allauth's login rate limits, so this view limits attempts both
per client address and per submitted username. The per-username limit still
holds when an attacker rotates addresses or spoofs ``X-Forwarded-For``.
"""

import hashlib

from django.conf import settings
from django.core.cache import caches
from rest_framework import status
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

THROTTLE_CACHE_ALIAS = "api_token_auth_throttle"


def submitted_username(request):
    try:
        return request.data.get("username")
    except Exception:  # unparsable body or non-object JSON
        return None


class TokenAuthThrottle(SimpleRateThrottle):
    """Keep counters in a dedicated cache when one is configured.

    Production defines it, so that unrelated cache traffic cannot cull the
    counters. Other settings fall back to the default cache.
    """

    @property
    def cache(self):
        return caches[THROTTLE_CACHE_ALIAS if THROTTLE_CACHE_ALIAS in settings.CACHES else "default"]


class TokenAuthClientThrottle(TokenAuthThrottle):
    """Limit token requests per client address.

    ``get_ident`` honours ``REST_FRAMEWORK["NUM_PROXIES"]``, so only the
    address appended by the trusted reverse proxy counts.
    """

    scope = "api_token_auth_client"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class TokenAuthUsernameThrottle(TokenAuthThrottle):
    """Limit token requests per submitted username, whatever the client address."""

    scope = "api_token_auth_username"

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None
        username = submitted_username(request)
        if not isinstance(username, str) or not username.strip():
            # Such requests cannot authenticate: the view rejects non-strings
            # and the serializer rejects blank usernames.
            return None
        # Hash the username so arbitrary input always yields a safe cache key.
        ident = hashlib.sha256(username.strip().casefold().encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ThrottledObtainAuthToken(ObtainAuthToken):
    throttle_classes = [TokenAuthClientThrottle, TokenAuthUsernameThrottle]

    def check_throttles(self, request):
        # Stop at the first refusal. DRF's default evaluates every throttle,
        # so a blocked client could still create a username counter per
        # request and flood the cache.
        for throttle in self.get_throttles():
            if not throttle.allow_request(request, self):
                self.throttled(request, throttle.wait())

    def post(self, request, *args, **kwargs):
        # DRF's CharField would turn a JSON number into a username, which the
        # username throttle does not count. Accept only string usernames.
        if not isinstance(submitted_username(request), str):
            return Response({"username": ["A string is required."]}, status=status.HTTP_400_BAD_REQUEST)
        return super().post(request, *args, **kwargs)


obtain_auth_token = ThrottledObtainAuthToken.as_view()
