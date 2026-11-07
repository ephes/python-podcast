"""Exercise real allauth routes without a provider exchange or external services."""

import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount import providers
from allauth.socialaccount.models import SocialAccount, SocialLogin
from allauth.socialaccount.providers.dummy.provider import DummyProvider
from django.contrib.auth import get_user_model
from django.urls import include, path, reverse

pytestmark = pytest.mark.django_db

# Keep the site's real account routes, but supply the dummy provider endpoints
# explicitly: allauth may have cached its provider URL list before this fixture.
urlpatterns = [
    path("_synthetic-provider/", include("allauth.socialaccount.providers.dummy.urls")),
    path("", include("config.urls")),
]


@pytest.fixture(autouse=True)
def signup_settings(settings, monkeypatch):
    settings.ROOT_URLCONF = __name__
    # Render the real signup form/closed templates with a minimal surrounding
    # layout so admission tests do not need the unrelated player/Vite assets.
    settings.TEMPLATES = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "APP_DIRS": False,
            "OPTIONS": {
                "context_processors": ["django.template.context_processors.request"],
                "loaders": [
                    (
                        "django.template.loaders.locmem.Loader",
                        {"account/base.html": "{% block inner %}{% endblock %}"},
                    ),
                    "django.template.loaders.filesystem.Loader",
                    "django.template.loaders.app_directories.Loader",
                ],
            },
            "DIRS": settings.TEMPLATES[0]["DIRS"],
        }
    ]
    settings.ACCOUNT_EMAIL_VERIFICATION = "none"
    settings.SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
    settings.ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False
    providers.registry.load()
    monkeypatch.setitem(providers.registry.provider_map, DummyProvider.id, DummyProvider)


def pending_social_signup(client):
    sociallogin = SocialLogin(
        user=get_user_model()(email="social@example.invalid"),
        account=SocialAccount(provider="dummy", uid="synthetic-identity"),
        provider=DummyProvider(request=None),
    )
    session = client.session
    session["socialaccount_sociallogin"] = sociallogin.serialize()
    session.save()


@pytest.mark.parametrize("opened", [False, True])
@pytest.mark.parametrize("route", ["account_signup", "socialaccount_signup"])
def test_signup_route_admission(client, settings, opened, route):
    settings.ACCOUNT_ALLOW_REGISTRATION = opened
    social = route == "socialaccount_signup"
    if social:
        pending_social_signup(client)
    before = (get_user_model().objects.count(), SocialAccount.objects.count(), EmailAddress.objects.count())
    response = client.get(reverse(route))
    assert response.status_code == 200
    assert ("account/signup_closed.html" in [t.name for t in response.templates]) is (not opened)
    if opened:
        assert "form" in response.context
    payload = {"username": "new-member", "email": "social@example.invalid" if social else "local@example.invalid"}
    if not social:
        payload.update(password1="synthetic-password-123", password2="synthetic-password-123")
    response = client.post(reverse(route), payload)
    if opened:
        assert response.status_code == 302
        user = get_user_model().objects.get(username="new-member")
        assert client.session["_auth_user_id"] == str(user.pk)
        assert SocialAccount.objects.count() == before[1] + int(social)
    else:
        assert response.status_code == 200
        assert "account/signup_closed.html" in [t.name for t in response.templates]
        assert (
            get_user_model().objects.count(),
            SocialAccount.objects.count(),
            EmailAddress.objects.count(),
        ) == before
        assert "_auth_user_id" not in client.session


def test_existing_account_can_log_in_while_signup_closed(client, settings):
    settings.ACCOUNT_ALLOW_REGISTRATION = False
    user = get_user_model().objects.create_user("existing", email="existing@example.invalid", password="test-password")
    response = client.post(reverse("account_login"), {"login": "existing", "password": "test-password"})
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)
    assert get_user_model().objects.count() == 1


def test_existing_social_account_can_log_in_while_signup_closed(client, settings):
    settings.ACCOUNT_ALLOW_REGISTRATION = False
    user = get_user_model().objects.create_user("existing", email="existing@example.invalid")
    SocialAccount.objects.create(user=user, provider="dummy", uid="123456")
    response = client.post(reverse("dummy_login"))
    assert response.status_code == 302
    response = client.post(response.url, {"id": "123456", "email": "existing@example.invalid"})
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)
    assert get_user_model().objects.count() == 1
    assert SocialAccount.objects.count() == 1
