"""The legacy helper's external boundaries are always synthetic."""

import importlib.util
import os
import runpy
import subprocess
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import commands

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prod_to_local.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("legacy_transfer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_is_inert(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("import attempted external work")

    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(SSHClient=forbidden))
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    monkeypatch.setattr("dotenv.load_dotenv", forbidden)
    runpy.run_path(str(SCRIPT), run_name="legacy_import")


@pytest.mark.parametrize("key", ["DATABASE_NAME", "POSTGRES_USER"])
@pytest.mark.parametrize("value", ["", "two words", "semi;colon", "-option", "$(touch nope)", "Upper", "x" * 64])
def test_invalid_identity_stops_before_fetch(monkeypatch, key, value):
    helper = load_helper()
    calls = []
    monkeypatch.setattr(helper, "fetch_backup", lambda *args: calls.append(args))
    env = {"PRODUCTION_HOST": "backup.invalid", "PRODUCTION_USERNAME": "test", "DATABASE_NAME": "podcast"}
    env["POSTGRES_USER"] = "local_role"
    env[key] = value
    with pytest.raises(ValueError):
        helper.transfer(env, replace_existing=False)
    assert calls == []


def test_restore_uses_literal_argv_and_explicit_connection_role(monkeypatch, tmp_path):
    helper = load_helper()
    path = tmp_path / "-backup $(touch nope); space.sql.gz"
    calls = []
    monkeypatch.setattr(helper.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    helper.restore_download(path, "podcast", "local_role", replace_existing=True)
    args, kwargs = calls[0]
    assert args[0] == [
        sys.executable,
        str(SCRIPT.parents[1] / "commands.py"),
        "restore-local-dump",
        str(path.resolve()),
        "--local-db-name",
        "podcast",
        "--replace-existing",
    ]
    assert kwargs["env"]["PGUSER"] == "local_role"
    assert kwargs["check"] is True
    assert not kwargs.get("shell")
    assert os.environ.get("PGUSER") != "local_role"


def test_transfer_does_not_swallow_restore_process_failure(monkeypatch, tmp_path):
    helper = load_helper()
    path = tmp_path / "dump.sql.gz"
    monkeypatch.setattr(helper, "fetch_backup", lambda *args: path)

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(2, args[0])

    monkeypatch.setattr(helper.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        helper.transfer(
            {
                "PRODUCTION_HOST": "backup.invalid",
                "PRODUCTION_USERNAME": "test",
                "DATABASE_NAME": "podcast",
                "POSTGRES_USER": "local_role",
            },
            replace_existing=False,
        )


def test_local_dump_command_delegates_confirmation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(commands, "_honcho_is_running", lambda: False)
    monkeypatch.setattr(commands, "_restore_dump_into_local_database", lambda *args: calls.append(args))
    path = tmp_path / "dump.sql.gz"
    result = CliRunner().invoke(commands.cli, ["restore-local-dump", str(path), "--replace-existing"])
    assert result.exit_code == 0, result.output
    assert calls == [(path, "python_podcast", True)]
