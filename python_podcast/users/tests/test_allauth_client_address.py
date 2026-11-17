"""allauth rate limits count the client address Traefik appends.

Traefik is the only reverse proxy in production, so every request reaches
gunicorn from ``127.0.0.1``. With allauth's default
``ALLAUTH_TRUSTED_PROXY_COUNT = 0`` every visitor shares that one address and
one per-address budget: a single client could exhaust it and lock everyone out
of ``/accounts/login/`` and the password reset. Production therefore trusts
the single Traefik hop (see ``tests/test_production_allauth_proxy.py``).
"""

import pytest
from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from python_podcast.users.tests.factories import UserFactory

PROXY = "127.0.0.1"
CLIENT_A = "203.0.113.1"
CLIENT_B = "203.0.113.2"


@pytest.fixture(autouse=True)
def clear_cache(minimal_account_templates):
    cache.clear()
    yield
    cache.clear()


def login(client_address, username, password="wrong-password", forwarded_for=None):
    return Client().post(
        reverse("account_login"),
        {"login": username, "password": password},
        REMOTE_ADDR=PROXY,
        HTTP_X_FORWARDED_FOR=forwarded_for or client_address,
    )


def exhaust_address_budget(client_address):
    # Distinct usernames, so only the per-address budget is used up.
    for attempt in range(2):
        assert login(client_address, f"nobody-{attempt}").status_code == 200
    assert login(client_address, "nobody-final").status_code == 429


def make_editor():
    editor = UserFactory(username="editor", email="editor@example.invalid")
    editor.set_password("correct-password")
    editor.save()
    EmailAddress.objects.create(user=editor, email=editor.email, primary=True, verified=True)
    return editor


@pytest.mark.django_db
@override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1, ACCOUNT_RATE_LIMITS={"login": "2/m/ip"})
def test_one_client_cannot_lock_another_client_out_of_login():
    make_editor()
    exhaust_address_budget(CLIENT_A)

    response = login(CLIENT_B, "editor", password="correct-password")

    assert response.status_code == 302


@pytest.mark.django_db
@override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1, ACCOUNT_RATE_LIMITS={"login": "2/m/ip"})
def test_forged_forwarded_for_prefix_does_not_escape_the_budget():
    exhaust_address_budget(CLIENT_A)

    # Only the last entry, appended by Traefik, is trusted.
    response = login(CLIENT_A, "nobody-forged", forwarded_for=f"198.51.100.7, {CLIENT_A}")
    assert response.status_code == 429


@pytest.mark.django_db
@override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=0, ACCOUNT_RATE_LIMITS={"login": "2/m/ip"})
def test_without_a_trusted_proxy_every_client_shares_the_proxy_budget():
    # The behaviour production had before trusting the Traefik hop.
    make_editor()
    exhaust_address_budget(CLIENT_A)

    assert login(CLIENT_B, "editor", password="correct-password").status_code == 429
