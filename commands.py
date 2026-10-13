import collections
import datetime
import gzip
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import webbrowser
import zlib
from pathlib import Path


def get_project_root():
    return Path(__file__).parent.resolve()


def bootstrap():
    """
    Called when first non-standard lib import fails.

    Given uv is installed, we need at least typer and rich to use this script.
    """
    if not (Path.cwd() / ".venv").exists():
        print("No .venv found, creating one using uv...")
        subprocess.run(["uv", "venv", ".venv"], check=True)
        print("Please activate the virtual environment and run the script again.")
        sys.exit(1)

    print("Sync requirements via uv...")
    subprocess.run(["uv", "sync"], check=True)


try:
    import typer
except ImportError:
    bootstrap()
    import typer

from rich import print  # noqa
from rich.markup import escape  # noqa

cli = typer.Typer()


def get_pythonpath():
    """Add project root and model directory to string"""
    project_root = str(get_project_root())
    model_root = str(Path(__file__).parent / "model")
    return f"{project_root}:{model_root}"


def env_with_pythonpath():
    """Get en environment dict with includes PYTHONPATH"""
    env = os.environ.copy()
    env["PYTHONPATH"] = get_pythonpath()
    return env


def _run_quality_tool(args, **kwargs):
    """Run a quality step, reporting startup errors and preserving failure status."""
    try:
        returncode = subprocess.call(args, **kwargs)
    except OSError as error:
        typer.echo(f"could not start {args[0]}: {error}", err=True)
        raise typer.Exit(1) from error
    if returncode:
        raise typer.Exit(returncode)


def _open_coverage_report(args):
    """Opening the generated report is best effort, including on headless systems."""
    try:
        returncode = subprocess.call(args)
    except OSError as error:
        typer.echo(f"could not start {args[0]}: {error}", err=True)
    else:
        if returncode:
            typer.echo(
                f"coverage viewer {args[0]} exited with status {returncode}; report: htmlcov/index.html", err=True
            )


@cli.command()
def mypy():
    """Run Mypy (configured in pyproject.toml)"""
    _run_quality_tool(["mypy", "."])


@cli.command()
def test():
    _run_quality_tool(["python", "-m", "pytest"], env=env_with_pythonpath())


@cli.command()
def coverage():
    """
    Run and show coverage.
    """
    _run_quality_tool(["coverage", "run", "-m", "pytest"], env=env_with_pythonpath())
    _run_quality_tool(["coverage", "html"])
    if platform.system() == "Darwin":
        _open_coverage_report(["open", "htmlcov/index.html"])
    elif platform.system() == "Linux" and "Microsoft" in platform.release():  # on WSL
        _open_coverage_report(["explorer.exe", r"htmlcov\index.html"])


@cli.command()
def jupyterlab():
    """
    Start a jupyterlab server.
    """
    project_root = get_project_root()
    notebook_dir = project_root / "notebooks"
    notebook_dir.mkdir(exist_ok=True)
    env = env_with_pythonpath()
    subprocess.call([sys.executable, "-m", "jupyterlab", "--notebook-dir", "notebooks/"], env=env)


@cli.command()
def update(upgrade: bool = typer.Option(True, "--upgrade/--no-upgrade")):
    """
    Update the requirements using uv.
    """
    print("Updating requirements via uv...")
    subprocess.call(["uv", "lock", "--upgrade"])


@cli.command()
def clean_build():
    commands = [
        ["rm", "-fr", "build/"],
        ["rm", "-fr", "dist/"],
        ["rm", "-fr", "*.egg-info"],
        ["rm", "-fr", "__pycache__"],
    ]
    for command in commands:
        subprocess.call(command)


@cli.command()
def clean_pyc():
    commands = [
        ["find", ".", "-name", "*.pyc", "-exec", "rm -f {} +"],
        ["find", ".", "-name", "*.pyo", "-exec", "rm -f {} +"],
        ["find", ".", "-name", "*~", "-exec", "rm -f {} +"],
    ]
    for command in commands:
        subprocess.call(command)


@cli.command()
def clean():
    clean_build()
    clean_pyc()


@cli.command()
def docs():
    """Build the documentation and fail on Sphinx warnings."""
    commands = [
        ["make", "-C", "docs", "clean"],
        ["make", "-C", "docs", "html", "SPHINXOPTS=-W --keep-going"],
    ]
    for command in commands:
        result = subprocess.run(command)
        if result.returncode:
            raise typer.Exit(result.returncode)
    file_url = "file://" + str(Path("docs/_build/html/index.html").resolve())
    webbrowser.open_new_tab(file_url)


class LocalRestoreError(Exception):
    """The local restore was refused or failed; the message says what state was left behind."""


_LOCAL_DB_NAME_PATTERN = re.compile(r"[a-z_][a-z0-9_]*")
_RESTORE_STAGING_SUFFIX = "_restore_staging"
_RESTORE_PREVIOUS_SUFFIX = "_restore_previous"
# PostgreSQL truncates identifiers to 63 bytes; keep room for the longest suffix.
_LOCAL_DB_NAME_MAX_LENGTH = 63 - len(_RESTORE_PREVIOUS_SUFFIX)
_PSQL = ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1"]


def _validate_local_db_name(local_db_name: str) -> None:
    if not _LOCAL_DB_NAME_PATTERN.fullmatch(local_db_name) or len(local_db_name) > _LOCAL_DB_NAME_MAX_LENGTH:
        raise LocalRestoreError(
            f"refusing to restore into {local_db_name!r}: use a lowercase name made of letters, digits and "
            f"underscores, at most {_LOCAL_DB_NAME_MAX_LENGTH} characters long"
        )


def _maintenance_sql(sql: str, *, capture: bool = False) -> str:
    """Run one statement against the local maintenance database and fail on any SQL error."""
    result = subprocess.run(
        [*_PSQL, "-A", "-t", "-d", "postgres", "-c", sql],
        check=True,
        stdout=subprocess.PIPE if capture else None,
        text=True,
    )
    return (result.stdout or "").strip() if capture else ""


def _local_database_exists(name: str) -> bool:
    # ``name`` passed _validate_local_db_name, so it cannot contain a quote.
    return _maintenance_sql(f"SELECT 1 FROM pg_database WHERE datname = '{name}'", capture=True) == "1"


def _check_local_restore_preconditions(local_db_name: str, replace_existing: bool) -> None:
    """Refuse a restore that is not explicitly confirmed or that would overwrite recovery data.

    Runs before the production dump is fetched and never changes anything.
    """
    _validate_local_db_name(local_db_name)
    staging = local_db_name + _RESTORE_STAGING_SUFFIX
    previous = local_db_name + _RESTORE_PREVIOUS_SUFFIX
    if _local_database_exists(previous):
        raise LocalRestoreError(
            f"recovery database {previous} exists, so an earlier restore was interrupted during the switch. "
            f"If {local_db_name} is missing, bring the old data back with "
            f'`psql -d postgres -c "ALTER DATABASE {previous} RENAME TO {local_db_name}"`; '
            f"if {local_db_name} is fine, remove the recovery copy with `dropdb {previous}`. Then rerun."
        )
    if _local_database_exists(staging):
        raise LocalRestoreError(
            f"staging database {staging} is left over from an interrupted restore. "
            f"It holds only restored dump data; remove it with `dropdb {staging}` and rerun."
        )
    if _local_database_exists(local_db_name) and not replace_existing:
        raise LocalRestoreError(
            f"local database {local_db_name} already exists and would be replaced. "
            "Rerun with --replace-existing to confirm, or pass another --local-db-name."
        )


def _verify_dump_file(backup_path: Path) -> None:
    """Check the dump is a complete gzip stream that looks like a finished pg_dump."""
    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise LocalRestoreError(f"dump {backup_path} is missing or empty; the local database was not touched")
    tail: collections.deque[bytes] = collections.deque(maxlen=20)
    try:
        with gzip.open(backup_path, "rb") as dump:
            for line in dump:
                tail.append(line)
    except (OSError, EOFError, zlib.error) as error:
        raise LocalRestoreError(
            f"dump {backup_path} is not a complete gzip file ({error}); the local database was not touched"
        ) from error
    if not any(line.startswith(b"-- PostgreSQL database dump complete") for line in tail):
        raise LocalRestoreError(
            f"dump {backup_path} does not end with the pg_dump completion marker, so it is truncated; "
            "the local database was not touched"
        )


def _drop_staging_database(staging: str) -> None:
    result = subprocess.run(["dropdb", "--if-exists", staging], check=False)
    if result.returncode:
        print(f"could not remove staging database {staging}; remove it with `dropdb {staging}`")


def _restore_dump_into_local_database(backup_path: Path, local_db_name: str, replace_existing: bool) -> None:
    """Load the dump into a staging database and switch it in only after a complete load.

    The existing local database is never dropped before the replacement is loaded and
    checked. During the switch it is kept under the recovery name and removed last.
    """
    _check_local_restore_preconditions(local_db_name, replace_existing)
    _verify_dump_file(backup_path)
    staging = local_db_name + _RESTORE_STAGING_SUFFIX
    previous = local_db_name + _RESTORE_PREVIOUS_SUFFIX

    subprocess.run(["createdb", staging], check=True)
    try:
        load = f"gunzip -c {shlex.quote(str(backup_path))} | psql -X -q -v ON_ERROR_STOP=1 -d {shlex.quote(staging)}"
        print(load)
        subprocess.run(["bash", "-o", "pipefail", "-c", load], check=True, stdout=subprocess.DEVNULL)
        table_count = subprocess.run(
            [*_PSQL, "-A", "-t", "-d", staging, "-c", "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        if not table_count.isdigit() or int(table_count) == 0:
            raise LocalRestoreError(f"dump {backup_path} restored no tables")
    except (subprocess.CalledProcessError, LocalRestoreError) as error:
        _drop_staging_database(staging)
        raise LocalRestoreError(
            f"loading {backup_path} failed ({error}); the local database {local_db_name} was not touched"
        ) from error
    except BaseException:
        _drop_staging_database(staging)
        raise

    # Re-check right before the switch: the confirmation must cover the database that is replaced.
    had_existing = _local_database_exists(local_db_name)
    if had_existing and not replace_existing:
        _drop_staging_database(staging)
        raise LocalRestoreError(
            f"local database {local_db_name} appeared during the restore and was not touched; "
            "rerun with --replace-existing to replace it"
        )
    if had_existing:
        try:
            _maintenance_sql(f'ALTER DATABASE "{local_db_name}" RENAME TO "{previous}"')
        except subprocess.CalledProcessError as error:
            _drop_staging_database(staging)
            raise LocalRestoreError(
                f"could not set aside {local_db_name} (close open connections to it and rerun); " "it was not changed"
            ) from error
    try:
        _maintenance_sql(f'ALTER DATABASE "{staging}" RENAME TO "{local_db_name}"')
    except subprocess.CalledProcessError as error:
        if not had_existing:
            raise LocalRestoreError(
                f"could not rename {staging} to {local_db_name}; the restored data is still in {staging}"
            ) from error
        try:
            _maintenance_sql(f'ALTER DATABASE "{previous}" RENAME TO "{local_db_name}"')
        except subprocess.CalledProcessError:
            raise LocalRestoreError(
                f"the switch failed half way: the previous data is in {previous} and the restored data in "
                f'{staging}. Recover the previous data with `psql -d postgres -c "ALTER DATABASE {previous} '
                f'RENAME TO {local_db_name}"`'
            ) from error
        _drop_staging_database(staging)
        raise LocalRestoreError(
            f"could not switch the restored data in; {local_db_name} was put back unchanged"
        ) from error
    if had_existing:
        result = subprocess.run(["dropdb", previous], check=False)
        if result.returncode:
            print(
                f"restore finished, but the previous data is still in {previous}; "
                f"remove it with `dropdb {previous}` before the next restore"
            )


def _fetch_production_dump(
    ssh_target: str, production_db_user: str, production_db_name: str, backup_path: Path
) -> None:
    remote_dump_pipeline = (
        "set -o pipefail; "
        f"sudo -u {shlex.quote(production_db_user)} "
        f"pg_dump --no-owner --no-privileges {shlex.quote(production_db_name)} | gzip -c"
    )
    remote_dump_command = f"bash -lc {shlex.quote(remote_dump_pipeline)}"
    print(f"Creating production backup via SSH: {ssh_target}:{production_db_name}")
    try:
        with backup_path.open("wb") as backup_file:
            subprocess.run(["ssh", ssh_target, remote_dump_command], stdout=backup_file, check=True)
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise


def _honcho_is_running() -> bool:
    import psutil

    for proc in psutil.process_iter(["pid", "name", "username"]):
        try:
            if "honcho" in " ".join(proc.cmdline()):
                return True
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            # ignore processes that we cannot observe
            pass
    return False


@cli.command()
def production_db_to_local(
    production_host: str = typer.Option("wersdoerfer.de", help="SSH host for the production server."),
    production_ssh_user: str = typer.Option("root", help="SSH user for the production server."),
    production_db_name: str = typer.Option("python-podcast", help="Production PostgreSQL database name."),
    production_db_user: str = typer.Option("postgres", help="Remote system user allowed to dump PostgreSQL."),
    local_db_name: str = typer.Option("python_podcast", help="Local PostgreSQL database name to restore into."),
    replace_existing: bool = typer.Option(
        False,
        "--replace-existing",
        help="Confirm that an existing local database with this name may be replaced.",
    ),
):
    """
    Fetch a production PostgreSQL dump over SSH and restore it locally.

    The dump is loaded into a staging database first. An existing local database
    is only replaced with --replace-existing, and only after the complete dump
    loaded without an SQL error.

    Make sure only the database is running using:
      just postgres
    """
    if _honcho_is_running():
        print("please stop honcho first and start a single postgres db with just postgres")
        sys.exit(1)

    try:
        _check_local_restore_preconditions(local_db_name, replace_existing)
    except LocalRestoreError as error:
        print(f"restore refused: {error}")
        raise typer.Exit(1) from error

    backups_dir = get_project_root() / "backups"
    backups_dir.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    backup_path = backups_dir / f"{timestamp}_{production_db_name}.sql.gz"
    ssh_target = f"{production_ssh_user}@{production_host}"
    _fetch_production_dump(ssh_target, production_db_user, production_db_name, backup_path)

    try:
        _restore_dump_into_local_database(backup_path, local_db_name, replace_existing)
    except LocalRestoreError as error:
        print(f"local restore failed: {error}")
        print(f"production backup was saved at {backup_path}")
        raise typer.Exit(1) from error
    print(backup_path)


_SECTION_HEADER_RE = re.compile(r"^\s*\[.*\]\s*(?:#.*)?$")


def _format_toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")


def _format_inline_table(table):
    parts = [f"{key} = {_format_toml_value(value)}" for key, value in table.items()]
    return "{ " + ", ".join(parts) + " }"


def _find_table_range(lines, header):
    start_idx = None
    for i, line in enumerate(lines):
        if line.split("#", 1)[0].strip() == header:
            start_idx = i
            break
    if start_idx is None:
        return None, None

    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if _SECTION_HEADER_RE.match(lines[i]) and lines[i].lstrip().startswith("["):
            end_idx = i
            break
    return start_idx, end_idx


_TOML_KEY_PART = r"""(?:"(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+)"""
_ASSIGNMENT_RE = re.compile(rf"[ \t]*({_TOML_KEY_PART})((?:[ \t]*\.[ \t]*{_TOML_KEY_PART})*)[ \t]*=")


class SourceSwitchError(Exception):
    """Switching package sources was refused or failed; the message says what state was left behind."""


def _unquote_toml_key(key):
    if key.startswith('"'):
        return tomllib.loads(f"{key} = 0").popitem()[0]
    if key.startswith("'"):
        return key[1:-1]
    return key


def _toml_value_end(text, pos):
    """Return the offset just past the line that ends the value starting at ``pos``.

    A value may continue over several lines: arrays, inline tables and multi-line
    strings. Brackets and comment markers inside strings do not count.
    """
    depth = 0
    length = len(text)
    while pos < length:
        char = text[pos]
        if text.startswith('"""', pos) or text.startswith("'''", pos):
            quote = text[pos] * 3
            pos += 3
            while pos < length and not text.startswith(quote, pos):
                pos += 2 if quote == '"""' and text[pos] == "\\" else 1
            pos += 3
            # Up to two more quotes may belong to the string content.
            while pos < length and text[pos] == quote[0]:
                pos += 1
            continue
        if char == '"':
            pos += 1
            while pos < length and text[pos] not in '"\n':
                pos += 2 if text[pos] == "\\" else 1
            if pos < length and text[pos] == '"':
                pos += 1
            continue
        if char == "'":
            pos += 1
            while pos < length and text[pos] not in "'\n":
                pos += 1
            if pos < length and text[pos] == "'":
                pos += 1
            continue
        if char == "#":
            while pos < length and text[pos] != "\n":
                pos += 1
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "\n" and depth <= 0:
            return pos + 1
        pos += 1
    return length


def _upsert_entries_in_table(pyproject_text, header, entries):
    """Replace or add ``key = value`` entries in the table ``header``.

    A replaced entry is removed completely, including a value that spans several
    lines. Everything else in the document is kept byte for byte.
    """
    lines = pyproject_text.splitlines(keepends=True)
    start_idx, _ = _find_table_range(lines, header)
    newline = "\r\n" if "\r\n" in pyproject_text else "\n"
    new_block = "".join(f"{key} = {value}{newline}" for key, value in entries.items())

    if start_idx is None:
        text = pyproject_text
        if text and not text.endswith("\n"):
            text += newline
        if text.strip():
            text += newline
        return f"{text}{header}{newline}{new_block}"

    body_start = sum(len(line) for line in lines[: start_idx + 1])
    text = pyproject_text
    length = len(text)
    kept = []
    pos = body_start
    table_end = length
    while pos < length:
        line_end = text.find("\n", pos)
        line_end = length if line_end == -1 else line_end + 1
        stripped = text[pos:line_end].strip()
        if stripped.startswith("["):
            table_end = pos
            break
        match = None if not stripped or stripped.startswith("#") else _ASSIGNMENT_RE.match(text, pos, line_end)
        if match is None:
            kept.append(text[pos:line_end])
            pos = line_end
            continue
        statement_end = _toml_value_end(text, match.end())
        is_replaced = not match.group(2) and _unquote_toml_key(match.group(1)) in entries
        if not is_replaced:
            kept.append(text[pos:statement_end])
        pos = statement_end

    body = "".join(kept)
    content = body.rstrip()
    trailing = body.removeprefix(content)
    if content:
        content += newline
        trailing = trailing.removeprefix("\r").removeprefix("\n")
    return text[:body_start] + content + new_block + trailing + text[table_end:]


def _parse_pyproject(text, description):
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise SourceSwitchError(
            f"{description} is not valid TOML ({error}); pyproject.toml was left unchanged."
        ) from error


def _write_text_atomically(path, text):
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copymode(path, tmp_path)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _update_uv_sources(pyproject_path, sources):
    """Set the given ``[tool.uv.sources]`` entries, or leave the file untouched.

    The proposed document is parsed before the file is replaced: it must be valid
    TOML, carry exactly the requested sources and differ from the original in
    nothing else. Otherwise ``SourceSwitchError`` is raised and no byte changes.
    """
    try:
        with open(pyproject_path, encoding="utf-8", newline="") as handle:
            original_text = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise SourceSwitchError(f"cannot read {pyproject_path} ({error}); nothing was changed.") from error
    original = _parse_pyproject(original_text, "pyproject.toml")

    entries = {name: _format_inline_table(source) for name, source in sources.items()}
    updated_text = _upsert_entries_in_table(original_text, "[tool.uv.sources]", entries)
    updated = _parse_pyproject(updated_text, "the updated pyproject.toml")

    tool = original.setdefault("tool", {})
    uv = tool.setdefault("uv", {}) if isinstance(tool, dict) else None
    expected_sources = uv.setdefault("sources", {}) if isinstance(uv, dict) else None
    if not isinstance(expected_sources, dict):
        raise SourceSwitchError("[tool.uv.sources] is not a table; pyproject.toml was left unchanged.")
    expected_sources.update(sources)
    if updated != original:
        raise SourceSwitchError(
            "the source entries could not be replaced without changing other settings; "
            "pyproject.toml was left unchanged."
        )
    _write_text_atomically(pyproject_path, updated_text)


def _sync_environment(args, pyproject_path):
    """Run ``uv sync`` and fail when it fails; ``pyproject.toml`` is not rolled back."""
    try:
        returncode = subprocess.run(args).returncode
    except OSError as error:
        returncode = 1
        detail = f"could not be started ({error})"
    else:
        detail = f"exited with status {returncode}"
    if returncode != 0:
        raise SourceSwitchError(
            f"`{' '.join(args)}` {detail}, so the installed environment was NOT updated. "
            f"{pyproject_path} keeps the new source entries; fix the problem and rerun this command, "
            "or run the opposite switch command to go back. Start it with `uv run --no-sync commands.py ...`: "
            "a plain `uv run` syncs first and fails the same way."
        )


def _fail_source_switch(error):
    print(f"source switch failed: {escape(str(error))}")
    raise typer.Exit(1) from error


@cli.command()
def switch_to_dev_environment():
    """
    Switch to development mode using local editable packages.

    Modifies pyproject.toml to use local paths in tool.uv.sources.
    """
    project_root = get_project_root()
    projects_dir = project_root.parent
    pyproject_path = project_root / "pyproject.toml"

    # Define local package mappings
    packages = [
        ("cast-vue", projects_dir / "cast-vue"),
        ("cast-bootstrap5", projects_dir / "cast-bootstrap5"),
        ("django-cast", projects_dir / "django-cast"),
        ("django-indieweb", projects_dir / "django-indieweb"),
    ]

    print("Switching to local development sources in pyproject.toml...")

    updates = {}
    for package_name, package_path in packages:
        if package_path.exists():
            updates[package_name] = {"path": f"../{package_path.name}", "editable": True}
            print(f"✓ {package_name} -> {package_path}")
        else:
            print(f"Warning: {package_path} does not exist, skipping")

    if updates:
        try:
            _update_uv_sources(pyproject_path, updates)
            print("\nRunning uv sync to apply changes...")
            _sync_environment(["uv", "sync"], pyproject_path)
        except SourceSwitchError as error:
            _fail_source_switch(error)

        print("\nDevelopment environment activated!")
        print("Local packages are now installed in editable mode.")
        print("Changes to the source code will be reflected immediately.")
        print("\nIMPORTANT: Remember to run prek hooks before committing!")
        print("To switch back to git sources, run: uv run python commands.py switch-to-git-sources")


@cli.command()
def switch_to_git_sources():
    """
    Switch back to git sources from local development mode.

    Restores original git sources in pyproject.toml.
    """
    project_root = get_project_root()
    pyproject_path = project_root / "pyproject.toml"

    # Define default git sources
    default_sources = {
        "cast-vue": {"git": "https://github.com/ephes/cast-vue"},
        "cast-bootstrap5": {"git": "https://github.com/ephes/cast-bootstrap5"},
        "django-cast": {"git": "https://github.com/ephes/django-cast", "branch": "develop"},
        "django-indieweb": {"git": "https://github.com/ephes/django-indieweb", "branch": "develop"},
    }

    print("Restoring git sources in pyproject.toml...")
    for package_name, git_source in default_sources.items():
        print(f"✓ {package_name} -> {git_source}")

    try:
        _update_uv_sources(pyproject_path, default_sources)
        print("\nRunning uv sync to apply changes...")
        _sync_environment(["uv", "sync", "--reinstall"], pyproject_path)
    except SourceSwitchError as error:
        _fail_source_switch(error)

    print("\nSwitched back to git sources!")
    print("All packages are now installed from their git repositories.")


if __name__ == "__main__":
    cli()
