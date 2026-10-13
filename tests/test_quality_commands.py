"""Quality commands must report failures and stop dependent coverage steps."""

from unittest.mock import Mock, call

import pytest
from typer.testing import CliRunner

import commands


@pytest.mark.parametrize("command", ["mypy", "test", "coverage"])
@pytest.mark.parametrize("code", [1, 7])
def test_tool_failure_exits_with_status(monkeypatch, command, code):
    run = Mock(return_value=code)
    monkeypatch.setattr(commands.subprocess, "call", run)

    result = CliRunner().invoke(commands.cli, [command])

    assert result.exit_code == code
    assert run.call_count == 1


@pytest.mark.parametrize("command", ["mypy", "test", "coverage"])
@pytest.mark.parametrize("error", [FileNotFoundError("missing tool"), PermissionError("not executable")])
def test_startup_failure_is_reported(monkeypatch, command, error):
    run = Mock(side_effect=error)
    monkeypatch.setattr(commands.subprocess, "call", run)

    result = CliRunner().invoke(commands.cli, [command])

    assert result.exit_code == 1
    assert "could not start" in result.output
    assert str(error) in result.output
    assert run.call_count == 1


@pytest.mark.parametrize("command,argv", [("mypy", ["mypy", "."]), ("test", ["python", "-m", "pytest"])])
def test_success_preserves_invocation(monkeypatch, command, argv):
    run = Mock(return_value=0)
    monkeypatch.setattr(commands.subprocess, "call", run)

    assert CliRunner().invoke(commands.cli, [command]).exit_code == 0
    kwargs = {"env": commands.env_with_pythonpath()} if command == "test" else {}
    run.assert_called_once_with(argv, **kwargs)


@pytest.mark.parametrize(
    "system,release,opener",
    [
        ("Darwin", "", ["open", "htmlcov/index.html"]),
        ("Linux", "Microsoft", ["explorer.exe", r"htmlcov\index.html"]),
        ("Linux", "generic", None),
    ],
)
def test_coverage_success_preserves_steps(monkeypatch, system, release, opener):
    run = Mock(return_value=0)
    monkeypatch.setattr(commands.subprocess, "call", run)
    monkeypatch.setattr(commands.platform, "system", lambda: system)
    monkeypatch.setattr(commands.platform, "release", lambda: release)

    assert CliRunner().invoke(commands.cli, ["coverage"]).exit_code == 0
    expected = [
        call(["coverage", "run", "-m", "pytest"], env=commands.env_with_pythonpath()),
        call(["coverage", "html"]),
    ]
    if opener:
        expected.append(call(opener))
    assert run.call_args_list == expected


@pytest.mark.parametrize("step", [1])
@pytest.mark.parametrize("failure", [5, FileNotFoundError("missing tool")])
def test_coverage_later_failure_stops_and_exits(monkeypatch, step, failure):
    run = Mock(side_effect=[0] * step + [failure])
    monkeypatch.setattr(commands.subprocess, "call", run)
    monkeypatch.setattr(commands.platform, "system", lambda: "Darwin")

    result = CliRunner().invoke(commands.cli, ["coverage"])

    assert result.exit_code == (failure if isinstance(failure, int) else 1)
    if isinstance(failure, OSError):
        assert "could not start" in result.output
    assert run.call_count == step + 1


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
@pytest.mark.parametrize("failure", [1, FileNotFoundError("missing viewer")])
def test_report_viewer_is_best_effort(monkeypatch, system, failure):
    run = Mock(side_effect=[0, 0, failure])
    monkeypatch.setattr(commands.subprocess, "call", run)
    monkeypatch.setattr(commands.platform, "system", lambda: system)
    monkeypatch.setattr(commands.platform, "release", lambda: "Microsoft")

    result = CliRunner().invoke(commands.cli, ["coverage"])

    assert result.exit_code == 0
    message = "exited with status 1" if isinstance(failure, int) else "could not start"
    assert message in result.output
    assert run.call_count == 3
