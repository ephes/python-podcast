import contextlib
import os
import platform
import re
import subprocess
import sys
import webbrowser
from pathlib import Path


def get_project_root():
    return Path(__file__).parent.resolve()


def _resolve_ops_control_path() -> Path:
    ops_control = os.environ.get("OPS_CONTROL")
    if ops_control:
        return Path(ops_control).expanduser()
    return get_project_root().parent / "ops-control"


def _ops_control_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PROJECTS_ROOT", str(get_project_root().parent))
    env.setdefault("SOPS_AGE_KEY_FILE", str(Path("~/.config/sops/age/keys.txt").expanduser()))
    return env


def _run_ops_control_playbook(
    playbook_name: str,
    *,
    target_host: str | None = None,
    extra_vars: dict[str, str] | None = None,
) -> None:
    ops_control_path = _resolve_ops_control_path()
    if not ops_control_path.exists():
        print(f"ops-control not found at {ops_control_path}. Set OPS_CONTROL to your clone path.")
        sys.exit(1)

    inventory_path = ops_control_path / "inventories" / "prod" / "hosts.yml"
    playbook_path = ops_control_path / "playbooks" / playbook_name
    if not inventory_path.exists():
        print(f"Missing ops-control inventory at {inventory_path}.")
        sys.exit(1)
    if not playbook_path.exists():
        print(f"Missing ops-control playbook at {playbook_path}.")
        sys.exit(1)

    ansible_playbook = os.environ.get("ANSIBLE_PLAYBOOK", "ansible-playbook")
    command = [ansible_playbook, "-i", str(inventory_path), str(playbook_path)]
    resolved_target_host = target_host or os.environ.get("OPS_CONTROL_HOST") or os.environ.get("TARGET_HOST")
    if resolved_target_host:
        command.extend(["-l", resolved_target_host])

    if resolved_target_host:
        extra_vars = dict(extra_vars or {})
        extra_vars.setdefault("target_host", resolved_target_host)
    if extra_vars:
        for key, value in extra_vars.items():
            command.extend(["-e", f"{key}={value}"])

    subprocess.call(command, cwd=ops_control_path, env=_ops_control_env())


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


@cli.command()
def mypy():
    """Run Mypy (configured in pyproject.toml)"""
    subprocess.call(["mypy", "."])


@cli.command()
def test():
    subprocess.call(["python", "-m", "pytest"], env=env_with_pythonpath())


@cli.command()
def coverage():
    """
    Run and show coverage.
    """
    subprocess.call(["coverage", "run", "-m", "pytest"], env=env_with_pythonpath())
    subprocess.call(["coverage", "html"])
    if platform.system() == "Darwin":
        subprocess.call(["open", "htmlcov/index.html"])
    elif platform.system() == "Linux" and "Microsoft" in platform.release():  # on WSL
        subprocess.call(["explorer.exe", r"htmlcov\index.html"])


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
    autogenerated = [
        "cast.api.rst",
        "cast.migrations.rst",
        "cast.rst",
        "cast.templatetags.rst",
        "modules.rst",
    ]
    for rst_name in autogenerated:
        (Path("docs") / rst_name).unlink(missing_ok=True)
    commands = [
        ["sphinx-apidoc", "-o", "docs/", "cast"],
        ["make", "-C", "docs", "clean"],
        ["make", "-C", "docs", "html"],
    ]
    for command in commands:
        subprocess.call(command)
    file_url = "file://" + str(Path("docs/_build/html/index.html").resolve())
    webbrowser.open_new_tab(file_url)


@contextlib.contextmanager
def working_directory(path):
    """Changes working directory and returns to previous on exit."""
    prev_cwd = Path.cwd().absolute()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(prev_cwd)


@cli.command()
def production_db_to_local():
    """
    Use ansible to create and fetch a backup.

    Make sure only the database is running using:
      postgres -D databases/postgres
    """
    import psutil

    for proc in psutil.process_iter(["pid", "name", "username"]):
        if proc.info["name"] is None or "python" not in proc.info["name"]:
            continue
        try:
            cmdline = " ".join(proc.cmdline())
            if "honcho" in cmdline:
                print("please stop honcho first and start a single postgres db with postgres -D databases/postgres")
                sys.exit(1)
        except psutil.AccessDenied:
            # ignore processes that we cannot observe
            pass

    deploy_root = Path(__file__).parent / "deploy"
    with working_directory(deploy_root):
        output = subprocess.check_output(
            ["ansible-playbook", "backup_database.yml", "--limit", "production"], text=True
        )
    [line] = [line for line in output.split("\n") if "sql.gz" in line]
    backup_file_name = line.split('"')[-2]
    backup_path = get_project_root() / "backups" / backup_file_name
    db_name = "python_podcast"
    subprocess.call(["dropdb", db_name])
    subprocess.call(["createdb", db_name])
    subprocess.call(["createuser", db_name])
    command = f"gunzip -c {backup_path} | psql {db_name}"
    print(command)
    subprocess.call(command, shell=True)
    print(backup_path)


@cli.command()
def make_local_db_restorable():
    """
    Make a local db restorable by ansible.

    Just print out help atm.
    """
    help = """
        pg_dump python_podcast | gzip > backups/db.staging.psql.gz
        cd deploy
        ansible-playbook restore_database.yml
    """
    print(help)


def deploy(environment):
    """
    Use legacy ansible-playbook flow under deploy/ (kept for reference).
    """
    deploy_root = Path(__file__).parent / "deploy"
    with working_directory(deploy_root):
        subprocess.call(["ansible-playbook", "deploy.yml", "--limit", environment])


@cli.command()
def deploy_staging():
    """
    Deploy staging using ops-control playbooks + SOPS.
    """
    _run_ops_control_playbook(
        "deploy-python-podcast.yml",
        target_host="staging",
        extra_vars={"service_secrets_env": "staging"},
    )


@cli.command()
def deploy_production():
    """
    Deploy production using ops-control playbooks + SOPS.
    """
    _run_ops_control_playbook("deploy-python-podcast.yml")


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


def _upsert_single_line_entries_in_table(pyproject_text, header, entries):
    lines = pyproject_text.splitlines(keepends=True)
    start_idx, end_idx = _find_table_range(lines, header)

    if start_idx is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(f"{header}\n")
        for key, value in entries.items():
            lines.append(f"{key} = {value}\n")
        return "".join(lines)

    table_start = start_idx + 1
    table_end = end_idx

    keys = set(entries.keys())
    for i in range(table_end - 1, table_start - 1, -1):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*=", line)
        if not match:
            continue
        if match.group(1) in keys:
            del lines[i]
            table_end -= 1

    insert_at = table_end
    while insert_at > table_start and not lines[insert_at - 1].strip():
        insert_at -= 1

    new_lines = [f"{key} = {value}\n" for key, value in entries.items()]
    lines[insert_at:insert_at] = new_lines
    return "".join(lines)


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

    sources_modified = False
    updates = {}
    for package_name, package_path in packages:
        if package_path.exists():
            updates[package_name] = _format_inline_table({"path": f"../{package_path.name}", "editable": True})
            print(f"✓ {package_name} -> {package_path}")
            sources_modified = True
        else:
            print(f"Warning: {package_path} does not exist, skipping")

    if sources_modified:
        pyproject_text = pyproject_path.read_text(encoding="utf-8")
        updated = _upsert_single_line_entries_in_table(pyproject_text, "[tool.uv.sources]", updates)
        pyproject_path.write_text(updated, encoding="utf-8")

        print("\nRunning uv sync to apply changes...")
        subprocess.call(["uv", "sync"])

        print("\nDevelopment environment activated!")
        print("Local packages are now installed in editable mode.")
        print("Changes to the source code will be reflected immediately.")
        print("\nIMPORTANT: Remember to run pre-commit hooks before committing!")
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
    updates = {}
    for package_name, git_source in default_sources.items():
        updates[package_name] = _format_inline_table(git_source)
        print(f"✓ {package_name} -> {git_source}")

    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    updated = _upsert_single_line_entries_in_table(pyproject_text, "[tool.uv.sources]", updates)
    pyproject_path.write_text(updated, encoding="utf-8")

    print("\nRunning uv sync to apply changes...")
    subprocess.call(["uv", "sync", "--reinstall"])

    print("\nSwitched back to git sources!")
    print("All packages are now installed from their git repositories.")


if __name__ == "__main__":
    cli()
