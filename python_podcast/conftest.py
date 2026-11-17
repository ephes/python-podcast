import pytest
from django.conf import settings
from django.test import RequestFactory

from python_podcast.users.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def media_storage(settings, tmpdir):
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user() -> settings.AUTH_USER_MODEL:
    return UserFactory()


@pytest.fixture
def request_factory() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def minimal_account_templates(settings):
    """Render allauth/Wagtail account pages without the site theme.

    The real ``account/base.html`` extends the theme base, which needs a
    configured site theme and Vite assets that account tests do not exercise.
    """
    settings.TEMPLATES = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "APP_DIRS": False,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                ],
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
