"""The legacy helper's external boundaries are always synthetic."""

import gzip
import importlib.util
import io
import os
import runpy
import signal
import stat
import subprocess
import sys
import time
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
    monkeypatch.setattr(helper, "check_restore", lambda *args, **kwargs: calls.append(args))
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
    monkeypatch.setattr(helper, "check_restore", lambda *args, **kwargs: None)

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


def test_precondition_check_uses_literal_argv_and_connection_role(monkeypatch):
    helper = load_helper()
    calls = []
    monkeypatch.setattr(helper.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    helper.check_restore("podcast", "local_role", replace_existing=False)
    args, kwargs = calls[0]
    assert args[0] == [
        sys.executable,
        str(SCRIPT.parents[1] / "commands.py"),
        "check-local-restore",
        "--local-db-name",
        "podcast",
    ]
    assert kwargs["env"]["PGUSER"] == "local_role"
    assert kwargs["check"] is True
    assert not kwargs.get("shell")


def test_refused_precondition_stops_before_contacting_production(monkeypatch):
    helper = load_helper()
    calls = []

    def refused(*args, **kwargs):
        calls.append("check")
        raise subprocess.CalledProcessError(1, ["check-local-restore"])

    monkeypatch.setattr(helper, "check_restore", refused)
    monkeypatch.setattr(helper, "fetch_backup", lambda *args: calls.append("fetch"))
    monkeypatch.setattr(helper, "restore_download", lambda *args, **kwargs: calls.append("restore"))
    with pytest.raises(subprocess.CalledProcessError):
        helper.transfer(
            {
                "PRODUCTION_HOST": "backup.invalid",
                "PRODUCTION_USERNAME": "test",
                "DATABASE_NAME": "podcast",
                "POSTGRES_USER": "local_role",
            }
        )
    assert calls == ["check"]


@pytest.mark.parametrize(
    "existing,replace,exit_code",
    [
        (set(), False, 0),
        ({"python_podcast"}, False, 1),
        ({"python_podcast"}, True, 0),
        ({"python_podcast", "python_podcast_restore_staging"}, True, 1),
        ({"python_podcast_restore_previous"}, True, 1),
    ],
)
def test_check_local_restore_command_changes_nothing(monkeypatch, existing, replace, exit_code):
    calls = []
    monkeypatch.setattr(commands, "_honcho_is_running", lambda: False)
    monkeypatch.setattr(commands, "_local_database_exists", lambda name: calls.append(name) or name in existing)
    monkeypatch.setattr(commands.subprocess, "run", lambda *args, **kwargs: pytest.fail("check ran a process"))
    arguments = ["check-local-restore"] + (["--replace-existing"] if replace else [])
    result = CliRunner().invoke(commands.cli, arguments)
    assert result.exit_code == exit_code, result.output
    assert calls


def test_check_local_restore_command_refuses_while_honcho_runs(monkeypatch):
    monkeypatch.setattr(commands, "_honcho_is_running", lambda: True)
    result = CliRunner().invoke(commands.cli, ["check-local-restore"])
    assert result.exit_code == 1


# Faithful minimal Paramiko seams: no connection or subprocess is started.
DUMP = gzip.compress(
    b"-- PostgreSQL database dump\nCREATE TABLE test (id int);\n" b"-- PostgreSQL database dump complete\n"
)
ANNOUNCEMENT = b"producer log\nscp python-podcast:site/backups/backup_test.sql.gz backups\n"


class RemoteFile(io.BytesIO):
    def __init__(self, owner):
        super().__init__(owner.data)
        self.owner = owner

    def stat(self):
        return self.owner.attrs()

    def read(self, size=-1):
        if self.owner.fault == "stalled-read":
            time.sleep(1)
        result = super().read(size)
        if self.owner.fault == "partial" and self.tell():
            raise OSError("synthetic interrupted download")
        return result

    def close(self):
        super().close()
        self.owner.close_resource("file")


class FakeSSH:
    def __init__(self, output=ANNOUNCEMENT, status=0, fault=None, data=DUMP):
        self.output = output
        self.error_output = b""
        self.status = status
        self.fault = fault
        self.data = data
        self.closed_resources = []
        self.calls = []
        self.channel = self
        self.closed = False

    def attrs(self):
        size = len(self.data) + (1 if self.fault == "wrong-size" else 0)
        mode = stat.S_IFLNK if self.fault == "symlink" else stat.S_IFREG
        return types.SimpleNamespace(st_size=size, st_mtime=123, st_mode=mode | 0o600)

    def load_system_host_keys(self):
        self.calls.append("host-keys")

    def connect(self, host, **kwargs):
        self.calls.append(("connect", host, kwargs))
        if self.fault == "stalled-connect":
            time.sleep(1)

    def get_transport(self):
        return self

    def open_session(self, **kwargs):
        self.calls.append(("session", kwargs))
        return self

    def settimeout(self, timeout):
        self.calls.append(("timeout", timeout))

    def exec_command(self, command, **kwargs):
        self.calls.append(("exec", command, kwargs))
        return self, io.BytesIO(self.output), io.BytesIO(b"")

    def recv_ready(self):
        return bool(self.output)

    def recv(self, maximum):
        result, self.output = self.output[:maximum], self.output[maximum:]
        return result

    def recv_stderr_ready(self):
        return bool(self.error_output)

    def recv_stderr(self, maximum):
        result, self.error_output = self.error_output[:maximum], self.error_output[maximum:]
        return result

    def exit_status_ready(self):
        if self.fault == "stalled-command":
            return False
        return True

    def recv_exit_status(self):
        return self.status

    def open_sftp(self):
        self.calls.append("sftp")
        return FakeSFTP(self)

    def close_resource(self, kind):
        self.closed_resources.append(kind)
        if self.fault == "close-" + kind:
            raise OSError("synthetic close failure: " + kind)

    def close(self):
        # The command channel and client use separate real objects; see fixture.
        self.close_resource("client")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeSFTP:
    def __init__(self, owner):
        self.owner = owner

    def get_channel(self):
        return self.owner

    def lstat(self, path):
        assert path == "site/backups/backup_test.sql.gz"
        return self.owner.attrs()

    def open(self, path, mode):
        assert mode == "rb"
        return RemoteFile(self.owner)

    def close(self):
        self.owner.close_resource("sftp")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def get(self, path, destination):
        Path(destination).write_bytes(self.owner.data[:10])
        if self.owner.fault:
            raise OSError("synthetic transfer failure")
        Path(destination).write_bytes(self.owner.data)


@pytest.fixture
def transport(monkeypatch):
    import paramiko

    helper = load_helper()

    def install(**kwargs):
        fake = FakeSSH(**kwargs)
        channel = types.SimpleNamespace(
            settimeout=fake.settimeout,
            exec_command=fake.exec_command,
            recv_ready=fake.recv_ready,
            recv=fake.recv,
            recv_stderr_ready=fake.recv_stderr_ready,
            recv_stderr=fake.recv_stderr,
            exit_status_ready=fake.exit_status_ready,
            recv_exit_status=fake.recv_exit_status,
            closed=True,
            close=lambda: fake.close_resource("channel"),
        )
        monkeypatch.setattr(fake, "open_session", lambda **kwargs: channel)
        monkeypatch.setattr(paramiko, "SSHClient", lambda: fake)
        monkeypatch.setattr(
            helper, "check_restore", lambda *args, **kwargs: fake.calls.append(("check", args, kwargs))
        )
        return fake

    return helper, install


@pytest.mark.parametrize(
    "output,status",
    [
        (ANNOUNCEMENT, 1),
        (ANNOUNCEMENT, -1),
        (ANNOUNCEMENT * 2, 0),
        (b"log with scp python-podcast:site/backups/backup_test.sql.gz backups\n", 0),
        (b"scp other:site/backups/backup_test.sql.gz backups\n", 0),
        (b"scp python-podcast:/etc/backup_test.sql.gz backups\n", 0),
        (b"scp python-podcast:site/backups/../backup_test.sql.gz backups\n", 0),
        (b"scp python-podcast:site/backups/-option.sql.gz backups\n", 0),
        (b"scp python-podcast:site/backups/$(touch_nope).sql.gz backups\n", 0),
        (b"x" * 65537 + ANNOUNCEMENT, 0),
    ],
)
def test_uncertain_producer_never_reaches_local_restore(transport, monkeypatch, tmp_path, output, status):
    helper, install = transport
    fake = install(output=output, status=status)
    monkeypatch.setattr(helper, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(helper, "restore_download", lambda *args, **kwargs: calls.append(args))
    with pytest.raises((ValueError, OSError, FileExistsError)):
        helper.transfer(
            {
                "PRODUCTION_HOST": "backup.invalid",
                "PRODUCTION_USERNAME": "test",
                "DATABASE_NAME": "podcast",
                "POSTGRES_USER": "local_role",
            }
        )
    assert calls == []
    assert "sftp" not in fake.calls
    assert "client" in fake.closed_resources
    assert list((tmp_path / "backups").iterdir()) == []


@pytest.mark.parametrize(
    "fault,error,message",
    [
        ("partial", OSError, "synthetic interrupted download"),
        ("wrong-size", ValueError, "backup download is incomplete"),
        ("symlink", ValueError, "regular nonempty file"),
        ("close-file", OSError, "synthetic close failure: file"),
        ("close-sftp", OSError, "synthetic close failure: sftp"),
        ("close-channel", OSError, "synthetic close failure: channel"),
        ("close-client", OSError, "synthetic close failure: client"),
    ],
)
def test_transfer_fault_preserves_previous_backup_and_prevents_restore(
    transport, monkeypatch, tmp_path, fault, error, message
):
    helper, install = transport
    fake = install(fault=fault)
    backups = tmp_path / "backups"
    backups.mkdir()
    # A different name: a collision with the announced name would refuse on its own.
    previous = backups / "backup_older.sql.gz"
    previous.write_bytes(b"previous backup")
    calls = []
    monkeypatch.setattr(helper, "ROOT", tmp_path)
    monkeypatch.setattr(helper, "restore_download", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(error, match=message):
        helper.transfer(
            {
                "PRODUCTION_HOST": "backup.invalid",
                "PRODUCTION_USERNAME": "test",
                "DATABASE_NAME": "podcast",
                "POSTGRES_USER": "local_role",
            }
        )
    assert calls == []
    assert previous.read_bytes() == b"previous backup"
    assert list(backups.iterdir()) == [previous]
    assert "client" in fake.closed_resources
    if "sftp" in fake.calls:
        assert "sftp" in fake.closed_resources


@pytest.mark.parametrize(
    "report_full_write,message",
    [(False, "short write"), (True, "staged backup size")],
)
def test_short_stage_write_preserves_previous_backup_and_prevents_restore(
    transport, monkeypatch, tmp_path, report_full_write, message
):
    helper, install = transport
    # Gzip accepts zero padding even if some of it is lost.
    padding = b"\0" * 8
    install(data=DUMP + padding)
    backups = tmp_path / "backups"
    backups.mkdir()
    previous = backups / "backup_older.sql.gz"
    previous.write_bytes(DUMP)
    monkeypatch.setattr(helper, "ROOT", tmp_path)
    monkeypatch.setattr(helper, "CHUNK", len(DUMP))
    fdopen = os.fdopen

    class ShortWriter(io.BufferedWriter):
        def write(self, data):
            if data == padding:
                written = super().write(data[:-1])
                return len(data) if report_full_write else written
            return super().write(data)

    monkeypatch.setattr(helper.os, "fdopen", lambda fd, mode: ShortWriter(fdopen(fd, mode, buffering=0)))

    def forbidden(*args, **kwargs):
        pytest.fail("attempted to publish or restore a partial backup")

    monkeypatch.setattr(helper.os, "link", forbidden)
    monkeypatch.setattr(helper, "restore_download", forbidden)
    with pytest.raises(OSError, match=message):
        helper.transfer(
            {
                "PRODUCTION_HOST": "backup.invalid",
                "PRODUCTION_USERNAME": "test",
                "DATABASE_NAME": "podcast",
                "POSTGRES_USER": "local_role",
            }
        )
    assert previous.read_bytes() == DUMP
    assert list(backups.iterdir()) == [previous]


@pytest.mark.parametrize("data", [b"", b"not gzip", DUMP[:-5], gzip.compress(b"unfinished SQL")])
def test_invalid_download_is_not_published(transport, tmp_path, data):
    helper, install = transport
    install(data=data)
    with pytest.raises((ValueError, OSError, EOFError)):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_success_closes_every_transport_before_publishing(transport, tmp_path, monkeypatch):
    helper, install = transport
    fake = install()
    original_link = os.link

    def publish(source, destination):
        assert set(fake.closed_resources) == {"file", "sftp", "channel", "client"}
        assert stat.S_IMODE(Path(source).stat().st_mode) == 0o600
        assert stat.S_IMODE(Path(source).parent.stat().st_mode) == 0o700
        original_link(source, destination)

    monkeypatch.setattr(helper.os, "link", publish)
    path = helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert path == tmp_path / "backup_test.sql.gz"
    assert path.read_bytes() == DUMP
    assert list(tmp_path.iterdir()) == [path]
    assert len(fake.closed_resources) == 4


def test_existing_final_name_is_never_overwritten(transport, tmp_path):
    helper, install = transport
    install()
    previous = tmp_path / "backup_test.sql.gz"
    previous.write_bytes(b"valuable previous bytes")
    with pytest.raises(FileExistsError):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert previous.read_bytes() == b"valuable previous bytes"
    assert list(tmp_path.iterdir()) == [previous]


@pytest.mark.parametrize(
    "fault,constant",
    [
        ("stalled-connect", "CONNECT_TIMEOUT"),
        ("stalled-command", "COMMAND_TIMEOUT"),
        ("stalled-read", "TRANSFER_TIMEOUT"),
    ],
)
def test_stalled_phase_is_interrupted_and_resources_close(transport, tmp_path, monkeypatch, fault, constant):
    helper, install = transport
    fake = install(fault=fault)
    monkeypatch.setattr(helper, constant, 0.02)
    with pytest.raises(TimeoutError):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert "client" in fake.closed_resources
    assert list(tmp_path.iterdir()) == []
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)


def test_stderr_output_has_the_same_bound(transport, tmp_path):
    helper, install = transport
    fake = install()
    fake.error_output = b"x" * 65537
    with pytest.raises(ValueError, match="output exceeds"):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert "sftp" not in fake.calls
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("constant", ["MAX_DOWNLOAD_BYTES", "MAX_SQL_BYTES"])
def test_byte_allowances_refuse_publication(transport, tmp_path, monkeypatch, constant):
    helper, install = transport
    install()
    monkeypatch.setattr(helper, constant, 10)
    with pytest.raises(ValueError):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_growth_and_metadata_change_are_refused(transport, tmp_path, monkeypatch):
    helper, install = transport
    fake = install()
    original_attrs = fake.attrs

    def shrinking_stat():
        attrs = original_attrs()
        attrs.st_size -= 1
        return attrs

    monkeypatch.setattr(fake, "attrs", shrinking_stat)
    with pytest.raises(ValueError, match="grew"):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert list(tmp_path.iterdir()) == []

    calls = 0

    def changing_stat():
        nonlocal calls
        calls += 1
        attrs = original_attrs()
        if calls > 2:
            attrs.st_mtime += 1
        return attrs

    fake = install()
    original_attrs = fake.attrs
    monkeypatch.setattr(fake, "attrs", changing_stat)
    with pytest.raises(ValueError, match="changed"):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_close_deadline_still_attempts_every_finalizer(transport, tmp_path, monkeypatch):
    helper, install = transport
    fake = install()
    monkeypatch.setattr(helper, "CLOSE_TIMEOUT", 0.02)
    original_close = fake.close_resource

    def stalled_close(kind):
        original_close(kind)
        if kind == "file":
            time.sleep(1)

    monkeypatch.setattr(fake, "close_resource", stalled_close)
    with pytest.raises(TimeoutError):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert fake.closed_resources == ["file", "sftp", "channel", "client"]
    assert list(tmp_path.iterdir()) == []


def test_phase_timer_restores_caller_handler(transport):
    helper, _ = transport
    previous = signal.getsignal(signal.SIGALRM)
    with pytest.raises(TimeoutError), helper._deadline(1):
        signal.raise_signal(signal.SIGALRM)
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)


def test_success_publishes_one_backup_before_one_restore(transport, monkeypatch, tmp_path):
    helper, install = transport
    fake = install()
    calls = []
    monkeypatch.setattr(helper, "ROOT", tmp_path)

    def restore(path, name, user, *, replace_existing):
        assert path.read_bytes() == DUMP
        assert fake.closed_resources == ["file", "sftp", "channel", "client"]
        calls.append((name, user, replace_existing))

    monkeypatch.setattr(helper, "restore_download", restore)
    helper.transfer(
        {
            "PRODUCTION_HOST": "backup.invalid",
            "PRODUCTION_USERNAME": "test",
            "DATABASE_NAME": "podcast",
            "POSTGRES_USER": "local_role",
        }
    )
    assert calls == [("podcast", "local_role", False)]
    assert fake.calls[0] == ("check", ("podcast", "local_role"), {"replace_existing": False})
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_exit_status_alone_does_not_end_announcement_admission(transport, monkeypatch, tmp_path):
    helper, install = transport
    fake = install()
    channel = fake.open_session()
    channel.closed = False

    def remaining_output(seconds):
        fake.output = ANNOUNCEMENT
        channel.closed = True

    monkeypatch.setattr(helper.time, "sleep", remaining_output)
    with pytest.raises(ValueError, match="exactly one"):
        helper.fetch_backup("backup.invalid", "test", tmp_path)
    assert "sftp" not in fake.calls
    assert list(tmp_path.iterdir()) == []
