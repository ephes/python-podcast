"""Run the synthetic Chromium media gate with a five-minute overall deadline."""

import os
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    "tests/e2e/test_custom_player.py::test_custom_player_in_browser",
    "tests/e2e/test_persistent_player.py::test_persistent_player_survives_navigation",
    "tests/e2e/test_persistent_player.py::test_delayed_transcripts_stay_with_the_active_episode",
]

# Exact pytest JUnit identities, including browser, theme and response ordering.
# Update alongside intentional selection/parameter changes and the independent
# synthetic report fixture in tests/test_core_media_gate.py.
EXPECTED_CASES = {
    ("tests.e2e.test_custom_player", "test_custom_player_in_browser[chromium]"),
    *{
        ("tests.e2e.test_persistent_player", f"test_persistent_player_survives_navigation[chromium-{theme}]")
        for theme in ("pp", "bootstrap5")
    },
    *{
        (
            "tests.e2e.test_persistent_player",
            f"test_delayed_transcripts_stay_with_the_active_episode[chromium-{theme}-{order}]",
        )
        for theme in ("pp", "bootstrap5")
        for order in ("old-first", "current-first")
    },
}


def run_gate(command, *, cwd, env, timeout=300):
    """Own the pytest session and its ordinary descendants on POSIX systems."""
    if os.name != "posix":
        raise OSError("Core media gate requires POSIX process groups (Linux/macOS).")
    process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    try:
        return subprocess.CompletedProcess(command, process.wait(timeout=timeout))
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            pass
        finally:
            # The leader may already have exited while a browser/server still
            # lives in the group. Always escalate for those remaining members.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
        raise


def main() -> int:
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.e2e",
        "DJANGO_ALLOW_ASYNC_UNSAFE": "1",
    }
    with TemporaryDirectory() as directory:
        report = Path(directory) / "core-media.xml"
        try:
            result = run_gate(
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
            identities = Counter((case.get("classname"), case.get("name")) for case in cases)
            if identities != Counter(EXPECTED_CASES) or any(
                case.find(tag) is not None for case in cases for tag in ("skipped", "failure", "error")
            ):
                print(
                    "Core media gate requires the exact seven required cases to pass without skips.", file=sys.stderr
                )
                return 1
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt, ET.ParseError) as error:
            print(f"Core media gate failed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
