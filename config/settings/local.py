import os
from pathlib import Path

import cast
import cast_bootstrap5
import cast_vue

from .base import *  # noqa
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env("DJANGO_SECRET_KEY", default="oZR3tCKbi2inATtN3v57IcSSd1O2mIJw3jqHrngLTn0W2RewNmA3lFFn7SYWSrH6")
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = [
    "localhost",
    "0.0.0.0",
    "127.0.0.1",
]

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": ""}}

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG  # noqa F405

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
# https://docs.djangoproject.com/en/dev/ref/settings/#email-host
EMAIL_HOST = "localhost"
# https://docs.djangoproject.com/en/dev/ref/settings/#email-port
EMAIL_PORT = 1025

# django-debug-toolbar
# ------------------------------------------------------------------------------
ENABLE_DEBUG_TOOLBAR = env.bool("DJANGO_DEBUG_TOOLBAR", default=False)
if ENABLE_DEBUG_TOOLBAR:
    # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
    INSTALLED_APPS += ["debug_toolbar"]  # noqa F405
    # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
    MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]  # noqa F405
    # https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
    DEBUG_TOOLBAR_CONFIG = {
        "DISABLE_PANELS": [
            "debug_toolbar.panels.redirects.RedirectsPanel",
        ],
        "SHOW_TEMPLATE_CONTEXT": True,
    }
    # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
    INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]

# Your stuff...
# ------------------------------------------------------------------------------

# django-cast styleguide (dev-only)
CAST_ENABLE_STYLEGUIDE = True
CAST_STYLEGUIDE_REMOTE_MEDIA = env.bool("CAST_STYLEGUIDE_REMOTE_MEDIA", default=True)
CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = [
    "https://wersdoerfer.de/blogs/ephes_blog/weeknotes-2025-11-03-shipping-steel-iq/",
    "https://wersdoerfer.de/blogs/ephes_blog/weeknotes-2025-08-18/",
]
CAST_STYLEGUIDE_VIDEO_SOURCE_URL = "https://wersdoerfer.de/blogs/ephes_blog/weeknotes-2025-02-03/"
CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://python-podcast.de/show/platonismus-und-python-data-class-builders/"
CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = (
    "https://python-podcast.de/show/platonismus-und-python-data-class-builders/transcript/"
)
CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS = 12
CAST_STYLEGUIDE_TRANSCRIPT_EXCERPT_SEGMENTS = 2
CAST_STYLEGUIDE_IMAGE_LIMIT = 6
CAST_STYLEGUIDE_REMOTE_TIMEOUT = 8
CAST_STYLEGUIDE_GENERATE_RENDITIONS = False
CAST_STYLEGUIDE_BODY_GALLERY_LIMIT = 2

# logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
        },
        "python-podcast": {
            "handlers": [
                "console",
            ],
            "propagate": True,
            "level": "DEBUG",
        },
    },
}

# Django Vite
DJANGO_VITE_ASSETS_PATH = "need to be set but doesn't matter"
DJANGO_VITE_DEV_MODE = env.bool("DJANGO_VITE_DEV_MODE", default=False)


def _package_manifest_path(package, *path_parts: str) -> Path:
    return Path(package.__file__).resolve().parent.joinpath("static", *path_parts, "manifest.json")


DJANGO_VITE = {
    "cast_vue": {
        "dev_mode": DJANGO_VITE_DEV_MODE,
        "static_url_prefix": "" if DJANGO_VITE_DEV_MODE else "cast_vue/",
        "manifest_path": _package_manifest_path(cast_vue, "cast_vue"),
    },
    "cast-bootstrap5": {
        "dev_mode": DJANGO_VITE_DEV_MODE,
        "dev_server_port": 5174,
        "static_url_prefix": "" if DJANGO_VITE_DEV_MODE else "cast_bootstrap5/vite/",
        "manifest_path": _package_manifest_path(cast_bootstrap5, "cast_bootstrap5", "vite"),
    },
    "cast": {
        "dev_mode": DJANGO_VITE_DEV_MODE,
        "static_url_prefix": "" if DJANGO_VITE_DEV_MODE else "cast/vite/",
        "manifest_path": _package_manifest_path(cast, "cast", "vite"),
    },
}
