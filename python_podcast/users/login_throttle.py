"""Failed-login throttle for the password login views outside allauth.

allauth rate-limits ``/accounts/login/``, but the Django admin login
(``ADMIN_URL``) and the Wagtail admin login (``WAGTAILADMIN_BASE_URL``) are
plain Django ``LoginView``\\ s with no limit of their own. Wrapping them with
:func:`throttle_failed_logins` limits failed attempts both per client address
and per submitted username, so the per-username limit still holds when an
attacker rotates addresses or spoofs ``X-Forwarded-For``.

The counters reuse the throttle cache and client-address logic of
``api/api-token-auth/`` (see :mod:`python_podcast.users.api_auth`). Only
failed attempts are counted, so routine successful logins never use up the
budget, but once a limit is reached every attempt is refused with ``429``,
including one with the correct password.
"""

import hashlib
import math
import unicodedata
from functools import wraps

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import HttpResponse

from python_podcast.users.api_auth import TokenAuthThrottle

LOGGED_IN_ATTR = "_login_throttle_logged_in"


@receiver(user_logged_in, dispatch_uid="python_podcast.users.login_throttle")
def _mark_logged_in(sender, request, user, **kwargs):
    # The wrapped view logs a user in only through django.contrib.auth.login,
    # which sends this signal with the very request object the wrapper holds.
    if request is not None:
        setattr(request, LOGGED_IN_ATTR, True)


class LoginFailureThrottle(TokenAuthThrottle):
    """Sliding-window counter of failed logins for one key.

    DRF's ``allow_request`` records every request it allows. Here checking
    and recording are separate, so only failures are recorded.
    """

    def __init__(self, ident):
        super().__init__()
        self.key = self.cache_format % {"scope": self.scope, "ident": ident}

    def _load(self):
        self.now = self.timer()
        self.history = [t for t in self.cache.get(self.key, []) if t > self.now - self.duration]

    def is_blocked(self):
        if self.rate is None:
            return False
        self._load()
        return len(self.history) >= self.num_requests

    def record_failure(self):
        if self.rate is None:
            return
        # Reload so that failures recorded by other workers in the meantime
        # are kept.
        self._load()
        self.history.insert(0, self.now)
        # Keep only what is needed to decide, so junk cannot grow an entry.
        while len(self.history) > self.num_requests:
            self.history.pop()
        self.cache.set(self.key, self.history, self.duration)

    def wait(self):
        # Seconds until the oldest failure that still counts expires.
        oldest = self.history[self.num_requests - 1]
        return max(oldest + self.duration - self.now, 1)


class AdminLoginClientThrottle(LoginFailureThrottle):
    """Failed logins per client address.

    ``get_ident`` honours ``REST_FRAMEWORK["NUM_PROXIES"]``, so only the
    address appended by the trusted reverse proxy counts.
    """

    scope = "admin_login_client"

    def __init__(self, request):
        super().__init__(self.get_ident(request))


class AdminLoginUsernameThrottle(LoginFailureThrottle):
    """Failed logins per submitted username, whatever the client address."""

    scope = "admin_login_username"

    def __init__(self, username):
        # Hash the username so arbitrary input always yields a safe cache key.
        super().__init__(hashlib.sha256(normalize_username(username).encode()).hexdigest())


def normalize_username(username):
    """Map every spelling the login form accepts for one account to one key.

    Django's ``AuthenticationForm`` applies NFKC before authenticating, so
    compatibility spellings such as full-width letters reach the same user.
    Case-folding errs towards sharing counters between usernames.
    """
    folded = unicodedata.normalize("NFKC", username).strip().casefold()
    return unicodedata.normalize("NFKC", folded)


def submitted_username(request):
    username = request.POST.get("username")
    if not isinstance(username, str) or not username.strip():
        # A blank username fails form validation before authentication.
        return None
    return username


def too_many_attempts(throttle):
    response = HttpResponse(
        "Too many failed login attempts. Try again later.",
        status=429,
        content_type="text/plain; charset=utf-8",
    )
    response["Retry-After"] = str(math.ceil(throttle.wait()))
    return response


def throttle_failed_logins(view):
    """Limit failed POSTs to a password login view per client and per username."""

    @wraps(view)
    def throttled_view(request, *args, **kwargs):
        if request.method != "POST":
            return view(request, *args, **kwargs)
        # Check the client limit first: a refused client neither reaches the
        # view nor creates a counter for the username it sent.
        throttles = [AdminLoginClientThrottle(request)]
        username = submitted_username(request)
        if username is not None:
            throttles.append(AdminLoginUsernameThrottle(username))
        for throttle in throttles:
            if throttle.is_blocked():
                return too_many_attempts(throttle)
        response = view(request, *args, **kwargs)
        if not getattr(request, LOGGED_IN_ATTR, False):
            for throttle in throttles:
                throttle.record_failure()
        return response

    throttled_view.login_throttled = True
    return throttled_view
