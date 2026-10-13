"""The locked dev environment can load the configured coverage plugins."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_configured_coverage_plugins_load(tmp_path):
    env = os.environ.copy()
    env["COVERAGE_FILE"] = str(tmp_path / ".coverage")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import coverage; " "cov = coverage.Coverage(config_file='.coveragerc'); " "cov.start(); cov.stop()",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
