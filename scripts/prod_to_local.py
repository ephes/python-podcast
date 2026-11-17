"""Legacy backup acquisition; SQL publication belongs to commands.py.

Run as ``python -m scripts.prod_to_local`` from the repository root.
Importing this module never loads configuration or performs external work.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fetch_backup(host, username, backups):
    import paramiko

    backups.mkdir(exist_ok=True)
    with paramiko.SSHClient() as client:
        client.load_system_host_keys()
        client.connect(host, username=username)
        _, stdout, _ = client.exec_command("cd site && python3 scripts/prod_backup.py")
        remote_path = None
        for line in stdout.read().decode("utf-8").splitlines():
            if "scp" in line:
                remote_path = line.split()[1].split(":")[-1]
        if remote_path is None:
            raise ValueError("backup producer did not announce a path")
        local_path = backups / Path(remote_path).name
        with client.open_sftp() as sftp:
            sftp.get(remote_path, str(local_path))
    return local_path


def restore_download(path, db_name, db_user, *, replace_existing):
    args = [
        sys.executable,
        str(ROOT / "commands.py"),
        "restore-local-dump",
        str(path.resolve()),
        "--local-db-name",
        db_name,
    ]
    if replace_existing:
        args.append("--replace-existing")
    subprocess.run(args, env={**os.environ, "PGUSER": db_user}, check=True)


def transfer(env, *, replace_existing=False):
    db_name = env.get("DATABASE_NAME", "")
    db_user = env.get("POSTGRES_USER", "")
    # Same database allowance as the maintained restore (room for recovery suffixes).
    for name, maximum in ((db_name, 46), (db_user, 63)):
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", name) or len(name) > maximum:
            raise ValueError("DATABASE_NAME / POSTGRES_USER must be lowercase PostgreSQL identifiers")
    host = env.get("PRODUCTION_HOST", "")
    username = env.get("PRODUCTION_USERNAME", "")
    if not host or not username:
        raise ValueError("PRODUCTION_HOST and PRODUCTION_USERNAME are required")
    path = fetch_backup(host, username, ROOT / "backups")
    restore_download(path, db_name, db_user, replace_existing=replace_existing)
    return path


def main():
    from dotenv import find_dotenv, load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-existing", action="store_true", help="Confirm replacement of an existing local DB")
    args = parser.parse_args()
    load_dotenv(find_dotenv())
    transfer(os.environ, replace_existing=args.replace_existing)


if __name__ == "__main__":
    main()
