import hashlib

import pytest
from django.core.cache import cache, caches
from django.test import Client, override_settings
from django.urls import resolve, reverse

from python_podcast.users import login_throttle
from python_podcast.users.tests.factories import UserFactory

RATES = {
    "admin_login_client": "5/hour",
    "admin_login_username": "3/hour",
}


@pytest.fixture(autouse=True)
def low_rates(monkeypatch):
    # DRF copies DEFAULT_THROTTLE_RATES onto the throttle classes at import
    # time, so patch the class attribute instead of overriding settings.
    monkeypatch.setattr(login_throttle.LoginFailureThrottle, "THROTTLE_RATES", RATES)
    cache.clear()
    yield
    cache.clear()


def make_user(**kwargs):
    # The project factory sets a random password; pin a known one.
    user = UserFactory(**kwargs)
    user.set_password("password")
    user.save()
    return user


def admin_login_url():
    return reverse("admin:login")


def wagtail_login_url():
    return reverse("wagtailadmin_login")


def post_login(url, username, password, ip="203.0.113.1", client=None, **extra):
    client = client or Client()
    return client.post(url, {"username": username, "password": password}, REMOTE_ADDR=ip, **extra)


def username_key(username):
    ident = hashlib.sha256(login_throttle.normalize_username(username).encode()).hexdigest()
    return f"throttle_admin_login_username_{ident}"


@pytest.mark.parametrize("url_name", ["admin:login", "wagtailadmin_login"])
def test_admin_login_urls_resolve_to_the_throttled_views(url_name):
    assert getattr(resolve(reverse(url_name)).func, "login_throttled", False)


@pytest.mark.django_db
def test_staff_login_to_django_admin_still_works():
    user = make_user(is_staff=True, is_superuser=True)
    client = Client()

    # The admin login form posts "next" as a hidden field.
    response = post_login(
        f"{admin_login_url()}?next={reverse('admin:index')}", user.username, "password", client=client
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("admin:index")
    # The dashboards need migrated Wagtail data, so check the session instead.
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_staff_login_to_wagtail_admin_still_works():
    user = make_user(is_staff=True, is_superuser=True)
    client = Client()

    response = post_login(wagtail_login_url(), user.username, "password", client=client)

    assert response.status_code == 302
    assert response["Location"] == reverse("wagtailadmin_home")
    # The dashboards need migrated Wagtail data, so check the session instead.
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_successful_logins_do_not_use_up_the_limits():
    user = make_user(is_staff=True, is_superuser=True)

    statuses = [post_login(admin_login_url(), user.username, "password").status_code for _ in range(8)]

    assert statuses == [302] * 8


@pytest.mark.django_db
def test_failed_guesses_for_one_username_are_throttled_across_client_addresses():
    user = make_user(is_staff=True, is_superuser=True)

    statuses = [
        post_login(admin_login_url(), user.username, "wrong", ip=f"203.0.113.{n}").status_code for n in range(1, 5)
    ]

    assert statuses == [200, 200, 200, 429]


@pytest.mark.django_db
def test_throttled_username_is_refused_even_with_the_correct_password():
    user = make_user(is_staff=True, is_superuser=True)
    client = Client()
    for _ in range(3):
        post_login(admin_login_url(), user.username, "wrong")

    response = post_login(
        admin_login_url(), f"  {user.username.upper()} ", "password", ip="198.51.100.9", client=client
    )

    assert response.status_code == 429
    assert 0 < int(response["Retry-After"]) <= 3600
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_compatibility_spellings_of_a_username_share_one_counter():
    # The login form applies NFKC, so full-width letters reach the same user.
    user = make_user(username="alice", is_staff=True, is_superuser=True)
    for n in range(3):
        post_login(admin_login_url(), "alice", "wrong", ip=f"203.0.113.{n}")
    client = Client()

    response = post_login(
        admin_login_url(), "\uff41\uff4c\uff49\uff43\uff45", "password", ip="198.51.100.9", client=client
    )

    assert response.status_code == 429
    assert "_auth_user_id" not in client.session
    assert user.username == "alice"


@pytest.mark.django_db
def test_failed_guesses_from_one_client_are_throttled_across_usernames():
    statuses = [post_login(wagtail_login_url(), f"user{n}", "wrong").status_code for n in range(6)]

    assert statuses == [200] * 5 + [429]


@pytest.mark.django_db
def test_django_admin_and_wagtail_logins_share_the_counters():
    user = make_user(is_staff=True, is_superuser=True)
    post_login(admin_login_url(), user.username, "wrong", ip="203.0.113.1")
    post_login(wagtail_login_url(), user.username, "wrong", ip="203.0.113.2")
    post_login(admin_login_url(), user.username, "wrong", ip="203.0.113.3")

    response = post_login(wagtail_login_url(), user.username, "password", ip="203.0.113.4")

    assert response.status_code == 429


@pytest.mark.django_db
def test_valid_credentials_of_a_non_staff_user_count_as_a_failure_at_the_django_admin():
    user = make_user()

    statuses = [
        post_login(admin_login_url(), user.username, "password", ip=f"203.0.113.{n}").status_code for n in range(4)
    ]

    assert statuses == [200, 200, 200, 429]


@pytest.mark.django_db
def test_failures_count_while_already_logged_in_as_another_user():
    # A session that is already authenticated must not hide failed guesses.
    other = make_user()
    client = Client()
    client.force_login(other)

    statuses = [
        post_login(admin_login_url(), "victim", "wrong", ip=f"203.0.113.{n}", client=client).status_code
        for n in range(4)
    ]

    assert statuses == [200, 200, 200, 429]


@pytest.mark.django_db
def test_get_requests_are_not_throttled():
    for n in range(6):
        post_login(admin_login_url(), f"user{n}", "wrong")

    assert Client().get(admin_login_url(), REMOTE_ADDR="203.0.113.1").status_code == 200
    assert Client().get(wagtail_login_url(), REMOTE_ADDR="203.0.113.1").status_code == 200


@pytest.mark.django_db
def test_throttled_client_does_not_create_username_counters():
    for n in range(5):
        post_login(admin_login_url(), f"user{n}", "wrong")

    response = post_login(admin_login_url(), "fresh-user", "wrong")

    assert response.status_code == 429
    assert cache.get(username_key("fresh-user")) is None


@pytest.mark.django_db
def test_client_limit_uses_the_proxy_appended_forwarded_address():
    # Traefik appends the real client address. Rotating a forged first entry
    # must not reset the client counter.
    statuses = [
        post_login(
            admin_login_url(),
            f"user{n}",
            "wrong",
            ip="10.0.0.2",
            HTTP_X_FORWARDED_FOR=f"192.0.2.{n}, 203.0.113.7",
        ).status_code
        for n in range(6)
    ]

    assert statuses == [200] * 5 + [429]
    other_client = post_login(admin_login_url(), "user-x", "wrong", ip="10.0.0.2", HTTP_X_FORWARDED_FOR="203.0.113.8")
    assert other_client.status_code == 200


@pytest.mark.django_db
def test_failures_are_recorded_per_hashed_username():
    post_login(admin_login_url(), "someone", "wrong")

    assert len(cache.get(username_key("someone"))) == 1


@pytest.mark.django_db
def test_counters_use_the_dedicated_throttle_cache_when_configured():
    locmem = "django.core.cache.backends.locmem.LocMemCache"
    caches_setting = {
        "default": {"BACKEND": locmem, "LOCATION": "default"},
        login_throttle.THROTTLE_CACHE_ALIAS: {"BACKEND": locmem, "LOCATION": "throttle"},
    }

    with override_settings(CACHES=caches_setting):
        post_login(admin_login_url(), "someone", "wrong")
        assert caches[login_throttle.THROTTLE_CACHE_ALIAS].get(username_key("someone"))
        assert caches["default"].get(username_key("someone")) is None
        caches[login_throttle.THROTTLE_CACHE_ALIAS].clear()


def test_throttle_cache_falls_back_to_default_and_keeps_the_legacy_alias():
    locmem = "django.core.cache.backends.locmem.LocMemCache"
    caches_setting = {
        "default": {"BACKEND": locmem, "LOCATION": "default"},
        "api_token_auth_throttle": {"BACKEND": locmem, "LOCATION": "throttle"},
    }

    with override_settings(CACHES=caches_setting):
        assert login_throttle.AdminLoginUsernameThrottle("someone").cache is caches["api_token_auth_throttle"]
    assert login_throttle.AdminLoginUsernameThrottle("someone").cache is caches["default"]


@pytest.mark.parametrize("kind", ["client", "username"])
def test_shared_failure_updates_wait_for_one_authority_and_retain_the_cap(tmp_path, kind):
    import multiprocessing
    import queue

    from django.test import RequestFactory
    from filelock import FileLock

    from python_podcast.users.tests.throttle_worker import record_failures

    cache_settings = {
        login_throttle.THROTTLE_CACHE_ALIAS: {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": str(tmp_path / "counters"),
            "OPTIONS": {"MAX_ENTRIES": 100000},
        }
    }
    lock_path = str(tmp_path / "counters.lock")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(5)
    reads = context.Queue()
    processes = [
        context.Process(target=record_failures, args=(cache_settings, lock_path, barrier, reads, kind))
        for _ in range(4)
    ]
    try:
        with FileLock(lock_path):
            for process in processes:
                process.start()
            barrier.wait(timeout=30)
            # A completed admission does not permit an unlocked history read.
            # The old implementation reads/writes immediately despite this lock.
            with pytest.raises(queue.Empty):
                reads.get(timeout=0.5)
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
        assert [reads.get(timeout=5) for _ in processes] == ["read"] * 4
        with override_settings(CACHES=cache_settings, ADMIN_LOGIN_THROTTLE_LOCK_PATH=lock_path):
            if kind == "username":
                throttle = login_throttle.AdminLoginUsernameThrottle("synthetic-user")
            else:
                throttle = login_throttle.AdminLoginClientThrottle(RequestFactory().post("/", REMOTE_ADDR="192.0.2.1"))
            throttle.num_requests = 3
            assert throttle.is_blocked()
            assert len(throttle.history) == 3
            assert 0 < throttle.wait() <= 3600
    finally:
        for process in processes:
            if process.pid and process.is_alive():
                process.terminate()
            if process.pid:
                process.join(timeout=5)
        reads.close()
        reads.join_thread()


def test_shared_counter_keeps_sliding_window_and_releases_lock_on_error(tmp_path, monkeypatch):
    cache_settings = {
        login_throttle.THROTTLE_CACHE_ALIAS: {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": str(tmp_path / "counters"),
        }
    }
    with override_settings(CACHES=cache_settings, ADMIN_LOGIN_THROTTLE_LOCK_PATH=str(tmp_path / "counter.lock")):
        throttle = login_throttle.AdminLoginUsernameThrottle("synthetic-user")
        monkeypatch.setattr(throttle, "timer", lambda: 10000)
        throttle.cache.set(throttle.key, [9990, 9990, 6400])
        assert not throttle.is_blocked()  # exact window boundary has expired
        throttle.record_failure()
        assert throttle.is_blocked()
        assert throttle.wait() == 3590
        with monkeypatch.context() as patch:
            patch.setattr(throttle.cache, "set", lambda *args: (_ for _ in ()).throw(OSError("synthetic failure")))
            with pytest.raises(OSError):
                throttle.record_failure()
        throttle.record_failure()  # error released the same lock
        assert len(throttle.cache.get(throttle.key)) == 3


def test_lock_timeout_refuses_login_before_authentication(monkeypatch):
    from django.http import HttpResponse
    from django.test import RequestFactory
    from filelock import Timeout

    def unavailable(self):
        raise Timeout("synthetic.lock")

    monkeypatch.setattr(login_throttle.LoginFailureThrottle, "counter_lock", unavailable)
    calls = []
    view = login_throttle.throttle_failed_logins(lambda request: calls.append(request) or HttpResponse())
    response = view(RequestFactory().post("/", {"username": "synthetic-user"}))
    assert response.status_code == 503
    assert response["Retry-After"] == "5"
    assert calls == []


def test_recording_admitted_failures_cannot_time_out(monkeypatch, tmp_path):
    from contextlib import contextmanager

    from django.http import HttpResponse
    from django.test import RequestFactory
    from filelock import Timeout

    authenticated = []
    waits = []

    @contextmanager
    def contended_lock(path, timeout):
        waits.append(timeout)
        if authenticated and timeout != -1:
            raise Timeout(path)
        yield

    def failed_login(request):
        authenticated.append(True)
        return HttpResponse("invalid credentials")

    monkeypatch.setattr(login_throttle, "FileLock", contended_lock)
    with override_settings(ADMIN_LOGIN_THROTTLE_LOCK_PATH=str(tmp_path / "synthetic.lock")):
        request = RequestFactory().post("/", {"username": "synthetic-user"}, REMOTE_ADDR="192.0.2.1")
        response = login_throttle.throttle_failed_logins(failed_login)(request)
        assert response.status_code == 200
        assert waits == [5, 5, -1, -1]
        for throttle in [
            login_throttle.AdminLoginClientThrottle(request),
            login_throttle.AdminLoginUsernameThrottle("synthetic-user"),
        ]:
            assert len(throttle.cache.get(throttle.key)) == 1
