"""Run the synthetic Chromium media gate with a five-minute overall deadline."""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    "tests/e2e/test_custom_player.py::test_custom_player_in_browser",
    "tests/e2e/test_persistent_player.py::test_persistent_player_survives_navigation",
    "tests/e2e/test_persistent_player.py::test_delayed_transcripts_stay_with_the_active_episode",
]


def main() -> int:
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.e2e",
        "DJANGO_ALLOW_ASYNC_UNSAFE": "1",
    }
    with TemporaryDirectory() as directory:
        report = Path(directory) / "core-media.xml"
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-p",
                    "no:sugar",
                    "-x",
                    "-m",
                    "",
                    "--migrations",
                    "--create-db",
                    "--browser",
                    "chromium",
                    f"--junitxml={report}",
                    *TESTS,
                ],
                cwd=ROOT,
                env=env,
                timeout=300,
            )
            if result.returncode:
                return result.returncode
            cases = list(ET.parse(report).iter("testcase"))
            if len(cases) != 7 or any(
                case.find(tag) is not None for case in cases for tag in ("skipped", "failure", "error")
            ):
                print("Core media gate requires all seven cases to pass without skips.", file=sys.stderr)
                return 1
        except (OSError, subprocess.TimeoutExpired, ET.ParseError) as error:
            print(f"Core media gate failed: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
