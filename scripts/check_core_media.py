"""Run the synthetic Chromium media gate with a five-minute overall deadline."""

import os
import signal
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
MAX_REPORT_BYTES = 1024 * 1024
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
        ("tests.e2e.test_persistent_player", f"test_persistent_player_survives_navigation[{theme}-chromium]")
        for theme in ("pp", "bootstrap5")
    },
    *{
        (
            "tests.e2e.test_persistent_player",
            f"test_delayed_transcripts_stay_with_the_active_episode[{theme}-chromium-{order}]",
        )
        for theme in ("pp", "bootstrap5")
        for order in ("old-first", "current-first")
    },
}


class ReportTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ET.ParseError("JUnit report must not contain a DOCTYPE")


def report_generation(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_report(report):
    # Nonblocking open lets us reject a FIFO without waiting for a writer.
    with open(report, "rb", opener=lambda path, flags: os.open(path, flags | os.O_NONBLOCK)) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError("JUnit report must be a regular file")
        if info.st_size > MAX_REPORT_BYTES:
            raise OSError("JUnit report exceeds 1 MiB")
        data = stream.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            raise OSError("JUnit report exceeds 1 MiB")
        final_info = os.fstat(stream.fileno())
        try:
            path_info = report.stat()
        except FileNotFoundError as error:
            raise OSError("JUnit report changed while being read") from error
        if len(data) != info.st_size or not (
            report_generation(info) == report_generation(final_info) == report_generation(path_info)
        ):
            raise OSError("JUnit report changed while being read")
    return ET.fromstring(data, parser=ET.XMLParser(target=ReportTreeBuilder()))


def passing_cases(root):
    expected_counts = {"tests": str(len(EXPECTED_CASES)), "failures": "0", "errors": "0", "skipped": "0"}
    suite = root
    if root.tag == "testsuites":
        if len(root) != 1 or any(root.get(name, count) != count for name, count in expected_counts.items()):
            raise ValueError("JUnit report must contain one passing suite")
        suite = root[0]
    if suite.tag != "testsuite" or any(suite.get(name) != count for name, count in expected_counts.items()):
        raise ValueError("JUnit suite counters must report seven passing tests")
    if any(child.tag not in {"testcase", "properties", "system-out", "system-err"} for child in suite):
        raise ValueError("Unexpected child in JUnit suite")
    if any(node.tag in {"skipped", "failure", "error"} for node in suite.iter()):
        raise ValueError("JUnit suite must not contain failures, errors or skips")
    cases = suite.findall("testcase")
    if len(cases) != sum(1 for _ in suite.iter("testcase")):
        raise ValueError("JUnit cases must be direct children of the suite")
    return cases


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
            try:
                root = read_report(report)
            except FileNotFoundError:
                print(
                    "Core media gate failed after pytest exited successfully: "
                    f"missing JUnit report proving that the exact {len(EXPECTED_CASES)} required cases passed.",
                    file=sys.stderr,
                )
                return 1
            cases = passing_cases(root)
            identities = Counter((case.get("classname"), case.get("name")) for case in cases)
            if identities != Counter(EXPECTED_CASES):
                print(
                    "Core media gate requires the exact seven required cases to pass without skips.", file=sys.stderr
                )
                return 1
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt, ET.ParseError, ValueError) as error:
            print(f"Core media gate failed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
