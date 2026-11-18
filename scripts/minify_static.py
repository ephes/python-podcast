"""Generate the committed minified persistent-player assets."""

import os
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout
from rcssmin import cssmin
from rjsmin import jsmin

ROOT = Path(__file__).resolve().parents[1]
PERSISTENT_CSS = ROOT / "python_podcast/static/css/persistent-player.css"
PERSISTENT_JS = ROOT / "python_podcast/static/js/persistent-player.js"
DOCK_MARKER = "/* ==========================================================================\n   The dock —"


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

    return {
        ROOT / "python_podcast/templates/cast/_persistent_player_critical.min.css": cssmin(critical_css) + "\n",
        ROOT / "python_podcast/static/css/persistent-player-dock.min.css": cssmin(marker + dock_css) + "\n",
        ROOT / "python_podcast/static/js/persistent-player.min.js": jsmin(PERSISTENT_JS.read_text()) + "\n",
    }


def main() -> None:
    lock = FileLock(ROOT / ".minify-static.lock")
    try:
        acquired = lock.acquire(timeout=0)
    except Timeout:
        raise SystemExit("Asset generation is already running in this checkout. Retry after it finishes.") from None
    with acquired:
        _publish_assets()


def _publish_assets() -> None:
    assets = minified_assets()
    temporary: set[Path] = set()
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    attempted: list[Path] = []
    error: BaseException | None = None

    def sibling(target: Path) -> Path:
        descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        path = Path(name)
        temporary.add(path)
        os.close(descriptor)
        return path

    try:
        # Generate the entire candidate and recovery set before touching any
        # published asset. Siblings keep each replace on the same filesystem.
        for target, content in assets.items():
            backup = None
            mode = 0o644
            if target.exists():
                mode = target.stat().st_mode & 0o777
                backup = sibling(target)
                backup.write_bytes(target.read_bytes())
                backup.chmod(mode)
            backups[target] = backup
            candidate = sibling(target)
            candidate.write_text(content, encoding="utf-8")
            candidate.chmod(mode)
            staged[target] = candidate
        for target, candidate in staged.items():
            attempted.append(target)
            os.replace(candidate, target)
    except BaseException as publication_error:
        error = publication_error
        for target in reversed(attempted):
            backup = backups[target]
            try:
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup, target)
            except BaseException as recovery_error:
                if backup is not None:
                    temporary.discard(backup)
                    error.add_note(f"Restore {target} from retained recovery copy {backup}: {recovery_error}")
                else:
                    error.add_note(f"Could not remove newly published {target}: {recovery_error}")
        raise
    finally:
        for path in temporary:
            try:
                path.unlink(missing_ok=True)
            except BaseException as cleanup_error:
                if error is None:
                    error = cleanup_error
                error.add_note(f"Could not clean up {path}: {cleanup_error}")
    if error is not None:
        raise error
    for target in assets:
        print(f"wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
