"""Tests for the local restore helper in commands.py.

Nothing here opens an SSH connection: the dump fetch is always replaced. The
PostgreSQL tests only use uniquely named throwaway databases.
"""

from __future__ import annotations

import gzip
import shutil
import subprocess
import uuid

import pytest
import typer
from django.conf import settings

import commands

VALID_DUMP = (
    b"-- PostgreSQL database dump\n"
    b"CREATE TABLE public.restored (id integer PRIMARY KEY, note text);\n"
    b"INSERT INTO public.restored VALUES (1, 'from production');\n"
    b"-- PostgreSQL database dump complete\n"
)
INVALID_SQL_DUMP = (
    b"-- PostgreSQL database dump\n"
    b"CREATE TABLE public.restored (id integer PRIMARY KEY, note text);\n"
    b"INSERT INTO public.missing_table VALUES (1);\n"
    b"INSERT INTO public.restored VALUES (1, 'after the error');\n"
    b"-- PostgreSQL database dump complete\n"
)


def write_dump(path, content=VALID_DUMP):
    path.write_bytes(gzip.compress(content))
    return path


class FakePostgres:
    """Stands in for subprocess.run and keeps a set of database names."""

    def __init__(self, databases=(), fail=()):
        self.databases = set(databases)
        self.fail = set(fail)
        self.calls: list[list[str]] = []
        self.restored_tables = "3"

    def _result(self, cmd, returncode=0, stdout="", check=False):
        if returncode and check:
            raise subprocess.CalledProcessError(returncode, cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout)

    def run(self, cmd, check=False, stdout=None, **kwargs):
        self.calls.append(list(cmd))
        tool = cmd[0]
        if tool == "ssh":
            if "ssh" in self.fail:
                return self._result(cmd, 255, check=check)
            stdout.write(gzip.compress(VALID_DUMP))
            return self._result(cmd)
        if tool == "createdb":
            assert cmd[1] not in self.databases
            self.databases.add(cmd[1])
            return self._result(cmd)
        if tool == "dropdb":
            name = cmd[-1]
            if f"dropdb:{name}" in self.fail:
                return self._result(cmd, 1, check=check)
            self.databases.discard(name)
            return self._result(cmd)
        if tool == "bash":
            return self._result(cmd, 1 if "load" in self.fail else 0, check=check)
        if tool == "psql":
            assert cmd[1:5] == ["-X", "-q", "-v", "ON_ERROR_STOP=1"]
            sql = cmd[-1]
            if sql.startswith("SELECT 1 FROM pg_database"):
                name = sql.split("'")[1]
                return self._result(cmd, stdout="1\n" if name in self.databases else "")
            if sql.startswith("SELECT count(*) FROM pg_tables"):
                return self._result(cmd, stdout=f"{self.restored_tables}\n")
            if sql.startswith("ALTER DATABASE"):
                source, target = sql.split('"')[1], sql.split('"')[3]
                if f"rename:{source}" in self.fail or source not in self.databases or target in self.databases:
                    return self._result(cmd, 1, check=check)
                self.databases.remove(source)
                self.databases.add(target)
                return self._result(cmd)
        raise AssertionError(f"unexpected command: {cmd}")

    def ran(self, *prefix):
        return [call for call in self.calls if call[: len(prefix)] == list(prefix)]


@pytest.fixture
def fake_postgres(monkeypatch):
    def install(**kwargs):
        fake = FakePostgres(**kwargs)
        monkeypatch.setattr(commands.subprocess, "run", fake.run)
        return fake

    return install


@pytest.fixture
def command_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(commands, "_honcho_is_running", lambda: False)
    monkeypatch.setattr(commands, "get_project_root", lambda: tmp_path)
    return tmp_path


def test_command_refuses_existing_database_without_confirmation_before_ssh(fake_postgres, command_environment):
    fake = fake_postgres(databases={"python_podcast"})

    with pytest.raises(typer.Exit) as excinfo:
        commands.production_db_to_local("prod.invalid", "root", "python-podcast", "postgres", "python_podcast", False)

    assert excinfo.value.exit_code == 1
    assert fake.ran("ssh") == []
    assert fake.ran("dropdb") == fake.ran("createdb") == []
    assert fake.databases == {"python_podcast"}
    assert not (command_environment / "backups").exists()


def test_command_replaces_confirmed_database_and_removes_recovery_copy_last(fake_postgres, command_environment):
    fake = fake_postgres(databases={"python_podcast"})

    commands.production_db_to_local("prod.invalid", "root", "python-podcast", "postgres", "python_podcast", True)

    assert fake.databases == {"python_podcast"}
    assert fake.ran("dropdb") == [["dropdb", "python_podcast_restore_previous"]]
    load_index = next(i for i, call in enumerate(fake.calls) if call[0] == "bash")
    first_rename = next(i for i, call in enumerate(fake.calls) if call[-1].startswith("ALTER DATABASE"))
    assert load_index < first_rename < fake.calls.index(["dropdb", "python_podcast_restore_previous"])
    assert "psql -X -q -v ON_ERROR_STOP=1 -d python_podcast_restore_staging" in fake.calls[load_index][-1]


def test_command_creates_missing_database_without_confirmation(fake_postgres, command_environment):
    fake = fake_postgres()

    commands.production_db_to_local("prod.invalid", "root", "python-podcast", "postgres", "python_podcast_prod", False)

    assert fake.databases == {"python_podcast_prod"}
    assert fake.ran("dropdb") == []


def test_command_failed_ssh_leaves_database_and_removes_partial_dump(fake_postgres, command_environment):
    fake = fake_postgres(databases={"python_podcast"}, fail={"ssh"})

    with pytest.raises(subprocess.CalledProcessError):
        commands.production_db_to_local("prod.invalid", "root", "python-podcast", "postgres", "python_podcast", True)

    assert fake.databases == {"python_podcast"}
    assert fake.ran("createdb") == fake.ran("dropdb") == []
    assert list((command_environment / "backups").iterdir()) == []


@pytest.mark.parametrize("name", ["", "Homepage", "home-page", "home page", 'x"; DROP', "a" * 60, "1abc"])
def test_unsafe_local_database_names_are_refused_without_any_command(fake_postgres, name):
    fake = fake_postgres(databases={"python_podcast"})

    with pytest.raises(commands.LocalRestoreError):
        commands._check_local_restore_preconditions(name, True)

    assert fake.calls == []


@pytest.mark.parametrize("leftover", ["python_podcast_restore_previous", "python_podcast_restore_staging"])
def test_leftover_restore_databases_block_a_new_restore(fake_postgres, tmp_path, leftover):
    fake = fake_postgres(databases={"python_podcast", leftover})

    with pytest.raises(commands.LocalRestoreError, match=leftover):
        commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), "python_podcast", True)

    assert fake.databases == {"python_podcast", leftover}
    assert fake.ran("dropdb") == fake.ran("createdb") == fake.ran("bash") == []


def test_corrupt_gzip_is_rejected_before_any_database_change(fake_postgres, tmp_path):
    fake = fake_postgres(databases={"python_podcast"})
    dump = tmp_path / "dump.sql.gz"
    dump.write_bytes(gzip.compress(VALID_DUMP * 200)[:-40])

    with pytest.raises(commands.LocalRestoreError, match="not a complete gzip"):
        commands._restore_dump_into_local_database(dump, "python_podcast", True)

    assert fake.databases == {"python_podcast"}
    assert fake.ran("createdb") == fake.ran("dropdb") == fake.ran("bash") == []


@pytest.mark.parametrize("content", [b"", b"-- PostgreSQL database dump\nCREATE TABLE public.t (id integer);\n"])
def test_dump_without_completion_marker_is_rejected(fake_postgres, tmp_path, content):
    fake = fake_postgres(databases={"python_podcast"})

    with pytest.raises(commands.LocalRestoreError, match="completion marker"):
        commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz", content), "python_podcast", True)

    assert fake.databases == {"python_podcast"}
    assert fake.ran("createdb") == []


def test_empty_dump_file_is_rejected(fake_postgres, tmp_path):
    fake = fake_postgres(databases={"python_podcast"})
    dump = tmp_path / "dump.sql.gz"
    dump.write_bytes(b"")

    with pytest.raises(commands.LocalRestoreError, match="missing or empty"):
        commands._restore_dump_into_local_database(dump, "python_podcast", True)

    assert fake.databases == {"python_podcast"}


def test_sql_error_during_load_keeps_existing_database_and_drops_staging(fake_postgres, tmp_path):
    fake = fake_postgres(databases={"python_podcast"}, fail={"load"})

    with pytest.raises(commands.LocalRestoreError, match="was not touched"):
        commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), "python_podcast", True)

    assert fake.databases == {"python_podcast"}
    assert fake.ran("dropdb") == [["dropdb", "--if-exists", "python_podcast_restore_staging"]]
    assert not [call for call in fake.calls if call[-1].startswith("ALTER DATABASE")]


def test_load_without_tables_keeps_existing_database(fake_postgres, tmp_path):
    fake = fake_postgres(databases={"python_podcast"})
    fake.restored_tables = "0"

    with pytest.raises(commands.LocalRestoreError, match="restored no tables"):
        commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), "python_podcast", True)

    assert fake.databases == {"python_podcast"}


def test_failed_set_aside_keeps_existing_database(fake_postgres, tmp_path):
    fake = fake_postgres(databases={"python_podcast"}, fail={"rename:python_podcast"})

    with pytest.raises(commands.LocalRestoreError, match="close open connections"):
        commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), "python_podcast", True)

    assert fake.databases == {"python_podcast"}
    assert ["dropdb", "python_podcast"] not in fake.calls


def test_failed_cutover_puts_existing_database_back(fake_postgres, tmp_path):
    fake = fake_postgres(databases={"python_podcast"}, fail={"rename:python_podcast_restore_staging"})

    with pytest.raises(commands.LocalRestoreError, match="put back unchanged"):
        commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), "python_podcast", True)

    assert fake.databases == {"python_podcast"}
    assert fake.ran("dropdb") == [["dropdb", "--if-exists", "python_podcast_restore_staging"]]


def test_failed_cutover_and_failed_rollback_keep_both_copies(fake_postgres, tmp_path):
    fake = fake_postgres(
        databases={"python_podcast"}, fail={"rename:python_podcast_restore_staging", "rename:python_podcast_restore_previous"}
    )

    with pytest.raises(commands.LocalRestoreError, match="python_podcast_restore_previous"):
        commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), "python_podcast", True)

    assert fake.databases == {"python_podcast_restore_previous", "python_podcast_restore_staging"}
    assert fake.ran("dropdb") == []


def test_failed_recovery_cleanup_still_reports_a_finished_restore(fake_postgres, tmp_path, capsys):
    fake = fake_postgres(databases={"python_podcast"}, fail={"dropdb:python_podcast_restore_previous"})

    commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), "python_podcast", True)

    assert fake.databases == {"python_podcast", "python_podcast_restore_previous"}
    assert "dropdb python_podcast_restore_previous" in " ".join(capsys.readouterr().out.split())


# --- real PostgreSQL -----------------------------------------------------------------


@pytest.fixture
def scratch_database(monkeypatch):
    """Yield an unused database name on the test server and drop every database derived from it."""
    if not all(shutil.which(tool) for tool in ("psql", "createdb", "dropdb", "gunzip", "bash")):
        pytest.skip("PostgreSQL client tools are not installed")
    database = settings.DATABASES["default"]
    for variable, key in (("PGHOST", "HOST"), ("PGPORT", "PORT"), ("PGUSER", "USER"), ("PGPASSWORD", "PASSWORD")):
        if database.get(key):
            monkeypatch.setenv(variable, str(database[key]))
    probe = subprocess.run(["psql", "-X", "-d", "postgres", "-c", "SELECT 1"], capture_output=True)
    if probe.returncode:
        pytest.skip("no local PostgreSQL maintenance database reachable")
    name = f"restore_test_{uuid.uuid4().hex[:12]}"
    try:
        yield name
    finally:
        for suffix in ("", "_restore_staging", "_restore_previous"):
            subprocess.run(["dropdb", "--if-exists", name + suffix], capture_output=True)


def psql_value(database, sql):
    return subprocess.run(
        ["psql", "-X", "-A", "-t", "-d", database, "-c", sql], check=True, capture_output=True, text=True
    ).stdout.strip()


def create_valuable_database(name):
    subprocess.run(["createdb", name], check=True)
    psql_value(name, "CREATE TABLE local_edits (note text); INSERT INTO local_edits VALUES ('valuable local row')")


def existing_databases(name):
    return set(psql_value("postgres", f"SELECT datname FROM pg_database WHERE datname LIKE '{name}%'").split())


def test_postgres_sql_error_in_dump_keeps_existing_rows(scratch_database, tmp_path):
    create_valuable_database(scratch_database)
    dump = write_dump(tmp_path / "dump.sql.gz", INVALID_SQL_DUMP)

    with pytest.raises(commands.LocalRestoreError, match="was not touched"):
        commands._restore_dump_into_local_database(dump, scratch_database, True)

    assert psql_value(scratch_database, "SELECT note FROM local_edits") == "valuable local row"
    assert existing_databases(scratch_database) == {scratch_database}


def test_postgres_unconfirmed_restore_keeps_existing_rows(scratch_database, tmp_path):
    create_valuable_database(scratch_database)

    with pytest.raises(commands.LocalRestoreError, match="--replace-existing"):
        commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), scratch_database, False)

    assert psql_value(scratch_database, "SELECT note FROM local_edits") == "valuable local row"
    assert existing_databases(scratch_database) == {scratch_database}


def test_postgres_confirmed_restore_replaces_database_after_complete_load(scratch_database, tmp_path):
    create_valuable_database(scratch_database)

    commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), scratch_database, True)

    assert psql_value(scratch_database, "SELECT note FROM restored") == "from production"
    assert psql_value(scratch_database, "SELECT to_regclass('public.local_edits') IS NULL") == "t"
    assert existing_databases(scratch_database) == {scratch_database}


def test_postgres_restore_into_new_database_needs_no_confirmation(scratch_database, tmp_path):
    commands._restore_dump_into_local_database(write_dump(tmp_path / "dump.sql.gz"), scratch_database, False)

    assert psql_value(scratch_database, "SELECT note FROM restored") == "from production"
    assert existing_databases(scratch_database) == {scratch_database}
