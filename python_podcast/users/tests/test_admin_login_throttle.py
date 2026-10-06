import hashlib

import pytest
from django.core.cache import cache, caches
from django.test import Client, override_settings
from django.urls import resolve, reverse

from python_podcast.users import api_auth, login_throttle
from python_podcast.users.tests.factories import UserFactory

RATES = {
    "api_token_auth_client": "5/hour",
    "api_token_auth_username": "3/hour",
    "admin_login_client": "5/hour",
    "admin_login_username": "3/hour",
}


@pytest.fixture(autouse=True)
def low_rates(monkeypatch):
    # DRF copies DEFAULT_THROTTLE_RATES onto the throttle classes at import
    # time, so patch the class attribute instead of overriding settings.
    monkeypatch.setattr(login_throttle.TokenAuthThrottle, "THROTTLE_RATES", RATES)
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
        api_auth.THROTTLE_CACHE_ALIAS: {"BACKEND": locmem, "LOCATION": "throttle"},
    }

    with override_settings(CACHES=caches_setting):
        post_login(admin_login_url(), "someone", "wrong")
        assert caches[api_auth.THROTTLE_CACHE_ALIAS].get(username_key("someone"))
        assert caches["default"].get(username_key("someone")) is None
        caches[api_auth.THROTTLE_CACHE_ALIAS].clear()
