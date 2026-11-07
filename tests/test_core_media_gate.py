"""Independent synthetic JUnit oracle for the local media gate."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

SPEC = importlib.util.spec_from_file_location(
    "core_media_gate", Path(__file__).parents[1] / "scripts/check_core_media.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

# Handwritten independently of the production allowlist; collection contract.
EXPECTED = [
    ("tests.e2e.test_custom_player", "test_custom_player_in_browser[chromium]"),
    ("tests.e2e.test_persistent_player", "test_persistent_player_survives_navigation[pp-chromium]"),
    ("tests.e2e.test_persistent_player", "test_persistent_player_survives_navigation[bootstrap5-chromium]"),
    (
        "tests.e2e.test_persistent_player",
        "test_delayed_transcripts_stay_with_the_active_episode[pp-chromium-old-first]",
    ),
    (
        "tests.e2e.test_persistent_player",
        "test_delayed_transcripts_stay_with_the_active_episode[pp-chromium-current-first]",
    ),
    (
        "tests.e2e.test_persistent_player",
        "test_delayed_transcripts_stay_with_the_active_episode[bootstrap5-chromium-old-first]",
    ),
    (
        "tests.e2e.test_persistent_player",
        "test_delayed_transcripts_stay_with_the_active_episode[bootstrap5-chromium-current-first]",
    ),
]


def write_report(report, identities=EXPECTED, status=None):
    suite = ET.Element("testsuite")
    for classname, name in identities:
        case = ET.SubElement(suite, "testcase", classname=classname, name=name)
        if status:
            ET.SubElement(case, status)
    ET.ElementTree(suite).write(report)


@pytest.mark.parametrize(
    "variant,valid",
    [
        ("expected", True),
        ("unrelated", False),
        ("duplicate", False),
        ("substitute", False),
        ("missing", False),
        ("extra", False),
        ("skipped", False),
        ("failure", False),
        ("error", False),
        ("malformed", False),
    ],
)
def test_report_contract(monkeypatch, capsys, variant, valid):
    reports = []

    def run(command, **kwargs):
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        reports.append(report)
        identities = list(EXPECTED)
        if variant == "unrelated":
            identities = [("unrelated", str(i)) for i in range(7)]
        elif variant == "duplicate":
            identities[-1] = identities[0]
        elif variant == "substitute":
            identities[-1] = (identities[-1][0], "wrong-parameter")
        elif variant == "missing":
            identities.pop()
        elif variant == "extra":
            identities.append(("extra", "test_extra"))
        if variant == "malformed":
            report.write_text("<broken>")
        else:
            write_report(report, identities, variant if variant in ("skipped", "failure", "error") else None)
        return SimpleNamespace(returncode=0)

    # Patch the launch boundary for both the old and repaired implementation.
    monkeypatch.setattr(gate.subprocess, "run", run)
    monkeypatch.setattr(gate, "run_gate", run, raising=False)
    assert gate.main() == (0 if valid else 1)
    assert reports and not reports[0].exists()
    if not valid:
        assert "Core media gate" in capsys.readouterr().err


@pytest.mark.parametrize(
    "failure", [7, FileNotFoundError("missing"), subprocess.TimeoutExpired("pytest", 300), KeyboardInterrupt()]
)
def test_launch_failure_cleans_report(monkeypatch, capsys, failure):
    reports = []

    def run(command, **kwargs):
        reports.append(Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))))
        if isinstance(failure, BaseException):
            raise failure
        return SimpleNamespace(returncode=failure)

    monkeypatch.setattr(gate.subprocess, "run", run)
    monkeypatch.setattr(gate, "run_gate", run, raising=False)
    assert gate.main() == (failure if isinstance(failure, int) else 1)
    assert not reports[0].parent.exists()


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("leader_exits", [False, True])
@pytest.mark.parametrize("group_gone", [False, True])
def test_timeout_and_interrupt_terminate_owned_group(monkeypatch, interrupted, leader_exits, group_gone):
    from unittest.mock import Mock, call

    failure = KeyboardInterrupt() if interrupted else subprocess.TimeoutExpired("pytest", 300)
    process = Mock(pid=12345)
    process.wait.side_effect = [failure, 0 if leader_exits else subprocess.TimeoutExpired("pytest", 2), 0]
    popen = Mock(return_value=process)
    killpg = Mock(side_effect=ProcessLookupError if group_gone else None)
    monkeypatch.setattr(gate, "os", SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(gate, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(gate.subprocess, "Popen", popen)
    with pytest.raises(type(failure)):
        gate.run_gate(["synthetic"], cwd="/synthetic", env={"SYNTHETIC": "1"})
    popen.assert_called_once_with(["synthetic"], cwd="/synthetic", env={"SYNTHETIC": "1"}, start_new_session=True)
    assert killpg.call_args_list == [call(12345, 15), call(12345, 9)]
    assert process.wait.call_args_list == [call(timeout=300), call(timeout=2), call(timeout=2)]


def test_success_preserves_exit_code(monkeypatch):
    from unittest.mock import Mock

    process = Mock()
    process.wait.return_value = 7
    killpg = Mock()
    monkeypatch.setattr(gate, "os", SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(gate.subprocess, "Popen", Mock(return_value=process))
    assert gate.run_gate(["synthetic"], cwd="/synthetic", env={}).returncode == 7
    killpg.assert_not_called()


def test_unsupported_platform_refuses_before_launch(monkeypatch):
    from unittest.mock import Mock

    popen = Mock()
    monkeypatch.setattr(gate, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(gate.subprocess, "Popen", popen)
    with pytest.raises(OSError, match="POSIX"):
        gate.run_gate(["synthetic"], cwd="/synthetic", env={})
    popen.assert_not_called()


@pytest.mark.parametrize("close_pipe", [False, True])
@pytest.mark.parametrize("interrupted", [False, True])
def test_synthetic_descendant_cleanup(monkeypatch, tmp_path, close_pipe, interrupted):
    """Real children on supported systems; fail-closed contract elsewhere."""
    import os
    import selectors
    import signal
    import sys
    import time

    import psutil

    if os.name != "posix":
        with pytest.raises(OSError, match="POSIX"):
            gate.run_gate([sys.executable, "-c", "raise AssertionError('launched')"], cwd=tmp_path, env={})
        return

    ready = tmp_path / "descendant.pid"
    child_script = """
import os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if sys.argv[2] == 'True':
    os.close(1)
    os.close(2)
Path(sys.argv[1]).write_text(str(os.getpid()))
while True: time.sleep(.1)
"""
    parent_script = """
import subprocess, sys, time
subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], sys.argv[3]])
while True: time.sleep(.1)
"""
    real_popen = subprocess.Popen
    processes = []

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        processes.append(process)
        wait = process.wait

        def interrupted_wait(*, timeout):
            # Only the initial gate wait is interrupted; cleanup waits are real.
            try:
                return wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.wait = wait
                raise KeyboardInterrupt() from None

        if interrupted:
            process.wait = interrupted_wait
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "synthetic descendant did not start"
        return process

    monkeypatch.setattr(gate.subprocess, "Popen", launch)
    try:
        failure = KeyboardInterrupt if interrupted else subprocess.TimeoutExpired
        with pytest.raises(failure):
            gate.run_gate(
                [sys.executable, "-c", parent_script, child_script, str(ready), str(close_pipe)],
                cwd=tmp_path,
                env=os.environ.copy(),
                timeout=0.1,
            )
        parent = processes[0]
        assert parent.returncode is not None  # direct child has been reaped
        with selectors.DefaultSelector() as selector:
            selector.register(parent.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=3), "a descendant still holds the pipe"
            assert parent.stdout.read(1) == b""
        descendant_pid = int(ready.read_text())
        deadline = time.monotonic() + 3
        while True:
            try:
                descendant = psutil.Process(descendant_pid)
                running = descendant.is_running() and descendant.status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                running = False
            if not running:
                break
            assert time.monotonic() < deadline, "owned descendant is still running"
            time.sleep(0.01)
    finally:
        # Even a regressed implementation must not leak the synthetic family.
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
            process.stdout.close()
