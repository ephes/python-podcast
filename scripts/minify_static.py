"""Generate the committed minified persistent-player assets."""

from pathlib import Path

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
    for target, content in minified_assets().items():
        target.write_text(content)
        print(f"wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
