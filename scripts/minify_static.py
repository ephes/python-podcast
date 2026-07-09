"""Generate the committed minified persistent-player assets."""

from pathlib import Path

from rcssmin import cssmin
from rjsmin import jsmin

ROOT = Path(__file__).resolve().parents[1]
ASSETS = (
    (
        ROOT / "python_podcast/static/css/persistent-player.css",
        ROOT / "python_podcast/static/css/persistent-player.min.css",
        cssmin,
    ),
    (
        ROOT / "python_podcast/static/js/persistent-player.js",
        ROOT / "python_podcast/static/js/persistent-player.min.js",
        jsmin,
    ),
)


def minified_assets() -> dict[Path, str]:
    """Return each generated path and its expected minified contents."""
    return {target: minifier(source.read_text()) + "\n" for source, target, minifier in ASSETS}


def main() -> None:
    for target, content in minified_assets().items():
        target.write_text(content)
        print(f"wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
