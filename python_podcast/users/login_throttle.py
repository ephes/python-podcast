"""Failed-login throttle for the password login views outside allauth.

allauth rate-limits ``/accounts/login/``, but the Django admin login
(``ADMIN_URL``) and the Wagtail admin login (``WAGTAILADMIN_BASE_URL``) are
plain Django ``LoginView``\\ s with no limit of their own. Wrapping them with
:func:`throttle_failed_logins` limits failed attempts both per client address
and per submitted username, so the per-username limit still holds when an
attacker rotates addresses or spoofs ``X-Forwarded-For``.

Only failed attempts are counted, so routine successful logins never use up the
budget, but once a limit is reached every attempt is refused with ``429``,
including one with the correct password.
"""

import hashlib
import math
import threading
import unicodedata
import uuid
from functools import wraps

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import ImproperlyConfigured
from django.dispatch import receiver
from django.http import HttpResponse
from filelock import FileLock, Timeout
from rest_framework.throttling import SimpleRateThrottle

# Keep the existing alias and directory so active admin lockouts survive
# removal of the token issuance endpoint.
THROTTLE_CACHE_ALIAS = "api_token_auth_throttle"

_local_counter_lock = threading.RLock()

# Recover capacity if a worker dies mid-authentication. An authentication still
# running beyond this lease may overlap a later attempt.
RESERVATION_SECONDS = 300

LOGGED_IN_ATTR = "_login_throttle_logged_in"


@receiver(user_logged_in, dispatch_uid="python_podcast.users.login_throttle")
def _mark_logged_in(sender, request, user, **kwargs):
    # The wrapped view logs a user in only through django.contrib.auth.login,
    # which sends this signal with the very request object the wrapper holds.
    if request is not None:
        setattr(request, LOGGED_IN_ATTR, True)


class LoginFailureThrottle(SimpleRateThrottle):
    """Sliding-window counter of failed logins for one key.

    DRF's ``allow_request`` records every request it allows. Here checking
    and recording are separate, so only failures are recorded.
    """

    @property
    def cache(self):
        return caches[THROTTLE_CACHE_ALIAS if THROTTLE_CACHE_ALIAS in settings.CACHES else "default"]

    def __init__(self, ident):
        super().__init__()
        self.key = self.cache_format % {"scope": self.scope, "ident": ident}

    def counter_lock(self, timeout=5):
        path = getattr(settings, "ADMIN_LOGIN_THROTTLE_LOCK_PATH", None)
        if path:
            # One stable lock for this cache, shared by all web workers. Never
            # unlink it: replacing its inode would split the locking authority.
            return FileLock(path, timeout=timeout)
        if isinstance(self.cache, LocMemCache):
            return _local_counter_lock
        raise ImproperlyConfigured("Shared login throttle caches require ADMIN_LOGIN_THROTTLE_LOCK_PATH")

    def _load(self):
        self.now = self.timer()
        self.history = [t for t in self.cache.get(self.key, []) if t > self.now - self.duration]
        self.reservations = {
            ident: expiry for ident, expiry in self.cache.get(self.key + "_inflight", {}).items() if expiry > self.now
        }

    def save_reservations(self):
        self.cache.set(self.key + "_inflight", self.reservations, RESERVATION_SECONDS)

    def is_blocked(self):
        if self.rate is None:
            return False
        with self.counter_lock():
            self._load()
            return len(self.history) + len(self.reservations) >= self.num_requests

    def record_failure(self):
        if self.rate is None:
            return
        # Authentication already ran: wait for ownership rather than dropping
        # an admitted failure on contention. Only pre-auth checks may time out.
        with self.counter_lock(timeout=-1):
            self._load()
            self._record_failure()

    def _record_failure(self):
        self.history.insert(0, self.now)
        self.history = self.history[: self.num_requests]
        self.cache.set(self.key, self.history, self.duration)

    def wait(self):
        expiries = [t + self.duration for t in self.history] + list(self.reservations.values())
        return max(min(expiries) - self.now, 1)


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


def reserve_attempt(throttles, reservation_id):
    """Check both budgets and reserve capacity under the same cache authority."""
    with throttles[0].counter_lock():
        for throttle in throttles:
            if throttle.rate is None:
                continue
            throttle._load()
            if len(throttle.history) + len(throttle.reservations) >= throttle.num_requests:
                return throttle
        for throttle in throttles:
            if throttle.rate is not None:
                throttle.reservations[reservation_id] = throttle.now + RESERVATION_SECONDS
                throttle.save_reservations()
    return None


def finish_attempt(throttles, reservation_id, *, failed):
    # Never drop an admitted failure or leave a live reservation on contention.
    with throttles[0].counter_lock(timeout=-1):
        for throttle in throttles:
            if throttle.rate is None:
                continue
            throttle._load()
            throttle.reservations.pop(reservation_id, None)
            if failed:
                throttle._record_failure()
            throttle.save_reservations()


def throttle_failed_logins(view):
    """Limit failed POSTs to a password login view per client and per username."""

    @wraps(view)
    def throttled_view(request, *args, **kwargs):
        try:
            return check_and_record(request, *args, **kwargs)
        except Timeout:
            response = HttpResponse("Login temporarily unavailable. Try again later.", status=503)
            response["Retry-After"] = "5"
            return response

    def check_and_record(request, *args, **kwargs):
        if request.method != "POST":
            return view(request, *args, **kwargs)
        # Check the client limit first: a refused client neither reaches the
        # view nor creates a counter for the username it sent.
        throttles = [AdminLoginClientThrottle(request)]
        username = submitted_username(request)
        if username is not None:
            throttles.append(AdminLoginUsernameThrottle(username))
        reservation_id = uuid.uuid4().hex
        blocked = reserve_attempt(throttles, reservation_id)
        if blocked is not None:
            return too_many_attempts(blocked)
        failed = False
        try:
            response = view(request, *args, **kwargs)
            failed = not getattr(request, LOGGED_IN_ATTR, False)
            return response
        finally:
            finish_attempt(throttles, reservation_id, failed=failed)

    throttled_view.login_throttled = True
    return throttled_view
