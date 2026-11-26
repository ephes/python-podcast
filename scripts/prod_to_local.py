"""Legacy backup acquisition; SQL publication belongs to commands.py.

Run as ``python -m scripts.prod_to_local`` from the repository root.
Importing this module never loads configuration or performs external work.
"""

import argparse
import gzip
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from contextlib import ExitStack, contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


CONNECT_TIMEOUT = 30
COMMAND_TIMEOUT = 60
TRANSFER_TIMEOUT = 300
CLOSE_TIMEOUT = 5
MAX_ANNOUNCEMENT_BYTES = 64 * 1024
MAX_DOWNLOAD_BYTES = 1024**3
MAX_SQL_BYTES = 4 * 1024**3
CHUNK = 64 * 1024
ANNOUNCEMENT = re.compile(r"scp python-podcast:(site/backups/[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}\.sql\.gz) backups")


@contextmanager
def _deadline(seconds):
    """Bound whole blocking phases, including drip-fed data and SSH request waits.

    This command-line helper requires POSIX and the main thread. Refuse an
    existing real-time alarm rather than consuming a caller's timer.
    """
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        raise ValueError("legacy transfer requires a POSIX main thread")
    if signal.getitimer(signal.ITIMER_REAL) != (0, 0):
        raise ValueError("legacy transfer cannot share an active real-time alarm")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(*args):
        raise TimeoutError("legacy transfer phase deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _close(resource):
    with _deadline(CLOSE_TIMEOUT):
        resource.close()


def _backup_announcement(channel):
    output = bytearray()
    total = 0
    while True:
        for ready, receive, keep in (
            (channel.recv_ready, channel.recv, True),
            (channel.recv_stderr_ready, channel.recv_stderr, False),
        ):
            if ready():
                data = receive(CHUNK)
                total += len(data)
                if total > MAX_ANNOUNCEMENT_BYTES:
                    raise ValueError("backup producer output exceeds 64 KiB")
                if keep:
                    output.extend(data)
        if (
            channel.exit_status_ready()
            and channel.closed
            and not channel.recv_ready()
            and not channel.recv_stderr_ready()
        ):
            break
        time.sleep(0.01)
    if channel.recv_exit_status() != 0:
        raise ValueError("backup producer did not exit successfully")
    paths = []
    for line in output.decode("utf-8").splitlines():
        match = ANNOUNCEMENT.fullmatch(line)
        if match:
            paths.append(match[1])
        elif line.lstrip().startswith("scp"):
            raise ValueError("unexpected backup announcement")
    if len(paths) != 1:
        raise ValueError("backup producer must announce exactly one backup")
    return paths[0]


def _backup_metadata(attrs):
    mode = getattr(attrs, "st_mode", None)
    size = getattr(attrs, "st_size", None)
    modified = getattr(attrs, "st_mtime", None)
    if (
        not isinstance(mode, int)
        or not stat.S_ISREG(mode)
        or not isinstance(size, int)
        or not 0 < size <= MAX_DOWNLOAD_BYTES
        or not isinstance(modified, int)
        or modified < 0
    ):
        raise ValueError("backup must have stable metadata and be a regular nonempty file of at most 1 GiB")
    return size, modified, mode


def _verify_download(path):
    """Bound decompression before accepting a complete pg_dump gzip stream."""
    total = 0
    tail = b""
    try:
        with gzip.open(path, "rb") as dump:
            while data := dump.read(CHUNK):
                total += len(data)
                if total > MAX_SQL_BYTES:
                    raise ValueError("backup SQL exceeds 4 GiB")
                tail = (tail + data)[-CHUNK:]
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError("backup is not a complete gzip stream") from error
    if not any(line.startswith(b"-- PostgreSQL database dump complete") for line in tail.splitlines()[-20:]):
        raise ValueError("backup has no pg_dump completion marker")


def fetch_backup(host, username, backups):
    import paramiko

    # Establish platform/timer admission before acquiring any external resource.
    with _deadline(CONNECT_TIMEOUT):
        pass
    backups.mkdir(exist_ok=True)
    if backups.is_symlink():
        raise ValueError("backup directory must not be a symlink")
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=backups) as directory:
        stage = Path(directory) / "dump.sql.gz"
        with ExitStack() as resources:
            client = paramiko.SSHClient()
            resources.callback(_close, client)
            with _deadline(CONNECT_TIMEOUT):
                client.load_system_host_keys()
                client.connect(
                    host,
                    username=username,
                    timeout=CONNECT_TIMEOUT,
                    auth_timeout=CONNECT_TIMEOUT,
                    banner_timeout=CONNECT_TIMEOUT,
                    channel_timeout=CONNECT_TIMEOUT,
                )
            with _deadline(COMMAND_TIMEOUT):
                channel = client.get_transport().open_session(timeout=COMMAND_TIMEOUT)
                resources.callback(_close, channel)
                channel.settimeout(COMMAND_TIMEOUT)
                channel.exec_command("cd site && python3 scripts/prod_backup.py")
                remote_path = _backup_announcement(channel)
            with _deadline(TRANSFER_TIMEOUT):
                sftp = client.open_sftp()
                resources.callback(_close, sftp)
                sftp.get_channel().settimeout(TRANSFER_TIMEOUT)
                expected = _backup_metadata(sftp.lstat(remote_path))
                remote = sftp.open(remote_path, "rb")
                resources.callback(_close, remote)
                if _backup_metadata(remote.stat()) != expected:
                    raise ValueError("backup changed before download")
                # Exclusive 0600 stage inside an exclusive 0700 directory.
                fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as destination:
                    total = 0
                    while data := remote.read(min(CHUNK, expected[0] - total + 1)):
                        total += len(data)
                        if total > expected[0]:
                            raise ValueError("backup grew during download")
                        if destination.write(data) != len(data):
                            raise OSError("short write while staging backup")
                    if total != expected[0]:
                        raise ValueError("backup download is incomplete")
                    if (
                        _backup_metadata(remote.stat()) != expected
                        or _backup_metadata(sftp.lstat(remote_path)) != expected
                    ):
                        raise ValueError("backup changed during download")
                    destination.flush()
                    if os.fstat(destination.fileno()).st_size != expected[0]:
                        raise OSError("staged backup size does not match remote size")
                    os.fsync(destination.fileno())
        # Every transport close must succeed before verification/publication.
        with _deadline(TRANSFER_TIMEOUT):
            _verify_download(stage)
        final = backups / Path(remote_path).name
        os.link(stage, final)  # Atomic, exclusive publication; never replace an old backup.
    return final


def _run_commands(arguments, db_name, db_user, replace_existing):
    args = [sys.executable, str(ROOT / "commands.py"), *arguments, "--local-db-name", db_name]
    if replace_existing:
        args.append("--replace-existing")
    subprocess.run(args, env={**os.environ, "PGUSER": db_user}, check=True)


def check_restore(db_name, db_user, *, replace_existing):
    """Refuse before contacting production when the maintained restore would refuse."""
    _run_commands(["check-local-restore"], db_name, db_user, replace_existing)


def restore_download(path, db_name, db_user, *, replace_existing):
    _run_commands(["restore-local-dump", str(path.resolve())], db_name, db_user, replace_existing)


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
    check_restore(db_name, db_user, replace_existing=replace_existing)
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
