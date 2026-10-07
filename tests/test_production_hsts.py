"""
HSTS policy of ``config.settings.production``.

The production settings need deploy-only environment variables, so they are
loaded in a subprocess with dummy values instead of being imported here.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DUMMY_PRODUCTION_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.production",
    "DJANGO_READ_DOT_ENV_FILE": "False",
    "DJANGO_SECRET_KEY": "test-only",
    "DATABASE_URL": "postgres:///unused",
    "DJANGO_AWS_ACCESS_KEY_ID": "test-only",
    "DJANGO_AWS_SECRET_ACCESS_KEY": "test-only",
    "DJANGO_AWS_STORAGE_BUCKET_NAME": "test-only",
    "CLOUDFRONT_DOMAIN": "cdn.example.invalid",
    "MAILGUN_API_KEY": "test-only",
    "MAILGUN_DOMAIN": "mg.example.invalid",
    "SENTRY_DSN": "",
    "DJANGO_ADMIN_URL": "admin/",
}

PROBE = """
import json
import django
from django.conf import settings
from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory

django.setup()
request = RequestFactory().get("/", secure=True)
response = SecurityMiddleware(lambda request: HttpResponse())(request)
print(json.dumps({
    "seconds": settings.SECURE_HSTS_SECONDS,
    "include_subdomains": settings.SECURE_HSTS_INCLUDE_SUBDOMAINS,
    "preload": settings.SECURE_HSTS_PRELOAD,
    "header": response.headers.get("Strict-Transport-Security"),
}))
"""


def load_production_hsts(tmp_path, **overrides):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    env.update(DUMMY_PRODUCTION_ENV)
    env["DJANGO_CACHE_LOCATION"] = str(tmp_path)
    env.update(overrides)
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_production_hsts_defaults_to_long_max_age_without_preload(tmp_path):
    hsts = load_production_hsts(tmp_path)

    assert hsts["seconds"] == 15552000  # 180 days, same as the Traefik middleware
    assert hsts["include_subdomains"] is True
    assert hsts["preload"] is False
    assert hsts["header"] == "max-age=15552000; includeSubDomains"


def test_production_hsts_preload_is_an_explicit_opt_in(tmp_path):
    hsts = load_production_hsts(
        tmp_path,
        DJANGO_SECURE_HSTS_SECONDS="31536000",
        DJANGO_SECURE_HSTS_PRELOAD="True",
    )

    assert hsts["header"] == "max-age=31536000; includeSubDomains; preload"
