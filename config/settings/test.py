"""
With these settings, tests run faster.
"""

from .base import *  # noqa
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = False
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env("DJANGO_SECRET_KEY", default="xOYgZOhgg95AaU3HhJtbHE6dqTZaDM9qIUhPmRxlrTXwBWq1aWnBwlTJIIVPqd2J")
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": ""}}

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES[0]["OPTIONS"]["debug"] = DEBUG  # noqa F405
TEMPLATES[0]["OPTIONS"]["loaders"] = [  # noqa F405
    (
        "django.template.loaders.cached.Loader",
        [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    )
]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# https://docs.djangoproject.com/en/dev/ref/settings/#email-host
EMAIL_HOST = "localhost"
# https://docs.djangoproject.com/en/dev/ref/settings/#email-port
EMAIL_PORT = 1025

TASKS = {
    "default": {
        "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
    },
    "cast_transcripts": {
        "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
    },
}

# Your stuff...
# ------------------------------------------------------------------------------

# STORAGE
# ------------------------------------------------------------------------------
# Tests must never write to the S3 media bucket. Keep uploads in memory so the
# suite runs without AWS credentials (CI) and never touches real media locally.
# Only the generic upload aliases are swapped; dedicated aliases such as
# cast_public_transcripts keep their configured backend so their config tests
# still exercise the real settings.
STORAGES = {
    **STORAGES,  # noqa F405
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "production": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
}
MEDIA_URL = "/media/"
