"""
django-indieweb proxy setting of ``config.settings.production``.

The production settings need deploy-only environment variables, so they are
loaded in a subprocess with dummy values instead of being imported here.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings

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
from django.conf import settings

print(settings.INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS)
"""


def load_production_proxy_hops(tmp_path, **overrides):
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
    return int(result.stdout.strip().splitlines()[-1])


def test_production_trusts_the_single_traefik_hop(tmp_path):
    assert load_production_proxy_hops(tmp_path) == 1


def test_production_proxy_hops_follow_the_shared_proxy_count(tmp_path):
    assert load_production_proxy_hops(tmp_path, DJANGO_NUM_PROXIES="2") == 2


def test_test_settings_keep_the_library_default():
    assert getattr(settings, "INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS", 0) == 0
