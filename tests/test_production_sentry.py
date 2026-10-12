"""
Sentry privacy options of ``config.settings.production``.

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
import sentry_sdk

django.setup()
options = sentry_sdk.get_client().options
print(json.dumps({
    "send_default_pii": options["send_default_pii"],
    "max_request_body_size": options["max_request_body_size"],
}))
"""


def load_production_sentry_options(tmp_path):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    env.update(DUMMY_PRODUCTION_ENV)
    env["DJANGO_CACHE_LOCATION"] = str(tmp_path)
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


def test_production_sentry_does_not_send_pii_or_request_bodies(tmp_path):
    options = load_production_sentry_options(tmp_path)

    assert options["send_default_pii"] is False
    assert options["max_request_body_size"] == "never"
