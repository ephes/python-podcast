"""Registration requires an explicit environment opt-in, without a database."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value, expected", [(None, False), ("true", True), ("false", False)])
def test_registration_requires_explicit_opt_in(value, expected):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DJANGO_READ_DOT_ENV_FILE": "False",
        "DATABASE_URL": "postgres:///unused",
        "DJANGO_AWS_ACCESS_KEY_ID": "test-only",
        "DJANGO_AWS_SECRET_ACCESS_KEY": "test-only",
        "DJANGO_AWS_STORAGE_BUCKET_NAME": "test-only",
        "CLOUDFRONT_DOMAIN": "cdn.example.invalid",
    }
    if value is not None:
        env["DJANGO_ACCOUNT_ALLOW_REGISTRATION"] = value
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from config.settings.base import ACCOUNT_ALLOW_REGISTRATION; "
            "print(json.dumps(ACCOUNT_ALLOW_REGISTRATION))",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is expected
