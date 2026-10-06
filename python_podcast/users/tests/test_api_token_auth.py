import hashlib

import pytest
from django.core.cache import cache, caches
from django.test import override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from python_podcast.users import api_auth
from python_podcast.users.tests.factories import UserFactory

TOKEN_URL = "/api/api-token-auth/"


@pytest.fixture(autouse=True)
def low_rates(monkeypatch):
    # DRF copies DEFAULT_THROTTLE_RATES onto the throttle classes at import
    # time, so patch the class attribute instead of overriding settings.
    monkeypatch.setattr(
        api_auth.SimpleRateThrottle,
        "THROTTLE_RATES",
        {"api_token_auth_client": "5/hour", "api_token_auth_username": "3/hour"},
    )
    cache.clear()
    yield
    cache.clear()


def make_user(**kwargs):
    # The project factory sets a random password; pin a known one.
    user = UserFactory(**kwargs)
    user.set_password("password")
    user.save()
    return user


def post_token(username, password, ip="203.0.113.1"):
    return APIClient().post(TOKEN_URL, {"username": username, "password": password}, REMOTE_ADDR=ip)


def test_token_auth_url_is_the_throttled_view():
    assert reverse("api-token-auth") == TOKEN_URL


@pytest.mark.django_db
def test_valid_credentials_still_return_a_token():
    user = make_user()

    response = post_token(user.username, "password")

    assert response.status_code == 200
    assert response.json()["token"] == Token.objects.get(user=user).key


@pytest.mark.django_db
def test_guesses_for_one_username_are_throttled_across_client_addresses():
    user = make_user()

    statuses = [post_token(user.username, "wrong", ip=f"203.0.113.{n}").status_code for n in range(1, 5)]

    assert statuses == [400, 400, 400, 429]
    # The correct password is refused too while the username is throttled.
    assert post_token(user.username, "password", ip="198.51.100.9").status_code == 429
    assert not Token.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_username_throttle_ignores_case_and_surrounding_whitespace():
    user = make_user(username="alice")

    statuses = [
        post_token(name, "wrong", ip=f"203.0.113.{n}").status_code
        for n, name in enumerate(["alice", "ALICE", " Alice ", "alice"], start=1)
    ]

    assert statuses[-1] == 429
    assert user.username == "alice"


@pytest.mark.django_db
def test_one_client_address_is_throttled_across_usernames():
    statuses = [post_token(f"user-{n}", "wrong").status_code for n in range(6)]

    assert statuses == [400] * 5 + [429]


@pytest.mark.django_db
def test_existing_token_header_still_authenticates_cast_api():
    staff = make_user(username="staff", is_staff=True)
    token = Token.objects.create(user=staff)
    url = reverse("cast:api:comment-training-data")

    anonymous = APIClient().get(url)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    authenticated = client.get(url)

    assert anonymous.status_code in (401, 403)
    assert authenticated.status_code == 200


@pytest.mark.django_db
def test_numeric_json_username_is_rejected_before_authentication():
    user = make_user(username="123")

    response = APIClient().post(TOKEN_URL, {"username": 123, "password": "password"}, format="json")

    assert response.status_code == 400
    assert not Token.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_forged_forwarded_for_prefixes_do_not_reset_the_client_counter():
    # Traefik appends the real client address; earlier entries are forged.
    statuses = [
        APIClient()
        .post(
            TOKEN_URL,
            {"username": f"user-{n}", "password": "wrong"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR=f"198.51.100.{n}, 203.0.113.7",
        )
        .status_code
        for n in range(6)
    ]

    assert statuses == [400] * 5 + [429]


def username_counter(username):
    throttle = api_auth.TokenAuthUsernameThrottle
    ident = hashlib.sha256(username.encode()).hexdigest()
    return cache.get(throttle.cache_format % {"scope": throttle.scope, "ident": ident})


@pytest.mark.django_db
def test_blocked_client_creates_no_username_counters():
    for n in range(5):
        post_token(f"user-{n}", "wrong")
    assert username_counter("user-0")

    blocked = [post_token(f"junk-{n}", "wrong").status_code for n in range(20)]

    assert blocked == [429] * 20
    assert all(username_counter(f"junk-{n}") is None for n in range(20))


def test_throttles_use_the_dedicated_cache_when_configured():
    locmem = "django.core.cache.backends.locmem.LocMemCache"
    caches_setting = {
        "default": {"BACKEND": locmem, "LOCATION": "default"},
        api_auth.THROTTLE_CACHE_ALIAS: {"BACKEND": locmem, "LOCATION": "throttle"},
    }

    with override_settings(CACHES=caches_setting):
        assert api_auth.TokenAuthClientThrottle().cache is caches[api_auth.THROTTLE_CACHE_ALIAS]
    assert api_auth.TokenAuthClientThrottle().cache is caches["default"]
