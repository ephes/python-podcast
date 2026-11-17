"""The Wagtail admin password reset shares allauth's ``reset_password`` limit.

Each accepted reset request sends an email, so without a limit anyone could
mail an editor's address (or burn the Mailgun quota) as often as they like.
"""

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import resolve, reverse

from python_podcast.users.password_reset import ThrottledWagtailPasswordResetView
from python_podcast.users.tests.factories import UserFactory

PROXY = "127.0.0.1"


@pytest.fixture(autouse=True)
def clear_cache(minimal_account_templates):
    cache.clear()
    yield
    cache.clear()


def wagtail_reset(email, client_address="203.0.113.1"):
    return Client().post(
        reverse("wagtailadmin_password_reset"),
        {"email": email},
        REMOTE_ADDR=PROXY,
        HTTP_X_FORWARDED_FOR=client_address,
    )


def allauth_reset(email, client_address="203.0.113.1"):
    return Client().post(
        reverse("account_reset_password"),
        {"email": email},
        REMOTE_ADDR=PROXY,
        HTTP_X_FORWARDED_FOR=client_address,
    )


def test_wagtail_password_reset_url_resolves_to_the_throttled_view():
    match = resolve(reverse("wagtailadmin_password_reset"))
    assert match.func.view_class is ThrottledWagtailPasswordResetView


def test_other_wagtail_password_reset_urls_are_unchanged():
    assert reverse("wagtailadmin_password_reset_done").endswith("/password_reset/done/")


@pytest.mark.django_db
@override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1, ACCOUNT_RATE_LIMITS={"reset_password": "20/m/ip,2/m/key"})
def test_repeated_resets_for_one_address_are_refused():
    user = UserFactory(email="editor@example.invalid", is_staff=True)

    assert wagtail_reset(user.email).status_code == 302
    assert wagtail_reset(user.email.upper(), client_address="203.0.113.2").status_code == 302
    response = wagtail_reset(user.email, client_address="203.0.113.3")

    assert response.status_code == 429
    assert len(mail.outbox) == 2


@pytest.mark.django_db
@override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1, ACCOUNT_RATE_LIMITS={"reset_password": "2/m/ip,20/m/key"})
def test_one_client_cannot_request_unlimited_resets_for_many_addresses():
    assert wagtail_reset("a@example.invalid").status_code == 302
    assert wagtail_reset("b@example.invalid").status_code == 302

    assert wagtail_reset("c@example.invalid").status_code == 429
    assert wagtail_reset("c@example.invalid", client_address="203.0.113.9").status_code == 302


@pytest.mark.django_db
@override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1, ACCOUNT_RATE_LIMITS={"reset_password": "20/m/ip,2/m/key"})
def test_wagtail_and_allauth_resets_share_one_budget_per_address():
    user = UserFactory(email="editor@example.invalid", is_staff=True)

    assert allauth_reset(user.email).status_code == 302
    assert wagtail_reset(user.email).status_code == 302

    assert wagtail_reset(user.email).status_code == 429
    assert allauth_reset(user.email).status_code == 429


@pytest.mark.django_db
def test_get_and_invalid_forms_are_not_limited():
    client = Client()
    assert client.get(reverse("wagtailadmin_password_reset")).status_code == 200
    with override_settings(ACCOUNT_RATE_LIMITS={"reset_password": "1/m/ip,1/m/key"}):
        for _ in range(3):
            response = client.post(reverse("wagtailadmin_password_reset"), {"email": "not-an-email"})
            assert response.status_code == 200
