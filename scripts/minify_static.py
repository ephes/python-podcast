"""Generate the committed minified persistent-player assets."""

import os
import re
import shutil
import stat
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout
from rcssmin import cssmin
from rjsmin import jsmin

ROOT = Path(__file__).resolve().parents[1]
PERSISTENT_CSS = ROOT / "python_podcast/static/css/persistent-player.css"
PERSISTENT_JS = ROOT / "python_podcast/static/js/persistent-player.js"
DOCK_MARKER = "/* ==========================================================================\n   The dock —"


def _asset_targets() -> tuple[Path, ...]:
    return (
        ROOT / "python_podcast/templates/cast/_persistent_player_critical.min.css",
        ROOT / "python_podcast/static/css/persistent-player-dock.min.css",
        ROOT / "python_podcast/static/js/persistent-player.min.js",
    )


def minified_assets() -> dict[Path, str]:
    """Return each generated path and its expected minified contents.

    Play-card rules are inlined because cards exist in the initial document.
    Dock rules are loaded asynchronously because the dock is hidden until the
    first explicit play action.
    """
    css = PERSISTENT_CSS.read_text()
    critical_css, marker, dock_css = css.partition(DOCK_MARKER)
    if not marker:
        raise RuntimeError(f"Dock marker not found in {PERSISTENT_CSS}")

    critical, dock, player = _asset_targets()
    return {
        critical: cssmin(critical_css) + "\n",
        dock: cssmin(marker + dock_css) + "\n",
        player: jsmin(PERSISTENT_JS.read_text()) + "\n",
    }


def main() -> None:
    lock = FileLock(ROOT / ".minify-static.lock")
    try:
        acquired = lock.acquire(timeout=0)
    except Timeout:
        raise SystemExit("Asset generation is already running in this checkout. Retry after it finishes.") from None
    with acquired:
        journal = ROOT / ".minify-static-transaction"
        targets = _asset_targets()
        _check_outputs(targets)
        _recover(journal, targets)
        _publish_assets(journal, targets)


def _check_outputs(targets: tuple[Path, ...]) -> None:
    unsupported = []
    for target in targets:
        try:
            info = target.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            unsupported.append(str(target.relative_to(ROOT)))
    if unsupported:
        paths = "\n".join(unsupported)
        raise RuntimeError(f"Asset outputs must be regular files without links. Check these paths:\n{paths}")


def _scratch(target: Path, transaction: Path) -> Path:
    # A sibling keeps even a separately mounted output on the same filesystem.
    return target.with_name(f".{target.name}.{transaction.name}")


def _recover(journal: Path, targets: tuple[Path, ...]) -> None:
    try:
        mode = journal.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(mode):
        raise RuntimeError(f"Unexpected asset recovery journal: {journal}")
    entries = list(journal.iterdir())
    if entries:
        if len(entries) != 1:
            raise RuntimeError(f"Unexpected asset recovery journal contents: {journal}")
        (transaction,) = entries
        if not re.fullmatch(r"[0-9a-f]{32}", transaction.name) or not stat.S_ISDIR(transaction.lstat().st_mode):
            raise RuntimeError(f"Unexpected asset recovery transaction: {transaction}")
        _finish_transaction(transaction, targets)
    journal.rmdir()


def _finish_transaction(transaction: Path, targets: tuple[Path, ...]) -> None:
    pending = transaction / "pending"
    if pending.exists():
        # A missing candidate records a successful replace. Keep each backup
        # until rollback completes so another interruption can retry the same
        # rollback even if it occurs just after a restore.
        for target in reversed(targets):
            scratch = _scratch(target, transaction)
            if (scratch / "candidate").exists():
                continue
            backup = scratch / "backup"
            try:
                if (scratch / "absent").exists():
                    target.unlink(missing_ok=True)
                else:
                    restored = scratch / "restore"
                    shutil.copy(backup, restored)
                    os.replace(restored, target)
            except BaseException as error:
                error.add_note(f"Could not restore {target}; recovery files retained in {scratch} (backup: {backup})")
                raise
        pending.unlink()
    for target in targets:
        scratch = _scratch(target, transaction)
        try:
            mode = scratch.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(mode):
            raise RuntimeError(f"Unexpected asset recovery directory: {scratch}")
        for name in ("candidate", "backup", "absent", "restore"):
            (scratch / name).unlink(missing_ok=True)
        scratch.rmdir()
    transaction.rmdir()


def _publish_assets(journal: Path, targets: tuple[Path, ...]) -> None:
    assets = minified_assets()
    journal.mkdir(mode=0o700)
    transaction = journal / uuid4().hex
    try:
        transaction.mkdir(mode=0o700)
        for target in targets:
            scratch = _scratch(target, transaction)
            scratch.mkdir(mode=0o700)
            mode = 0o644
            if target.exists():
                mode = target.stat().st_mode & 0o777
                backup = scratch / "backup"
                backup.write_bytes(target.read_bytes())
                backup.chmod(mode)
            else:
                (scratch / "absent").touch()
            candidate = scratch / "candidate"
            candidate.write_text(assets[target], encoding="utf-8")
            candidate.chmod(mode)

        # Only this phase can leave published assets needing a rollback.
        pending = transaction / "pending"
        pending.touch()
        for target in targets:
            os.replace(_scratch(target, transaction) / "candidate", target)
        pending.unlink()
    except BaseException as error:
        try:
            _recover(journal, targets)
        except BaseException as recovery_error:
            error.add_note(f"Could not finish asset recovery in {journal}: {recovery_error}")
            for note in getattr(recovery_error, "__notes__", ()):
                error.add_note(note)
        raise
    _recover(journal, targets)
    for target in targets:
        print(f"wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
