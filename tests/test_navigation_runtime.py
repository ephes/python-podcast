"""Transport/generation oracle without a browser; real DOM tests remain required."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="optional Node transport oracle")
@pytest.mark.parametrize("asset", ["persistent-player.js", "persistent-player.min.js"])
@pytest.mark.parametrize("case", ["oversize", "fragment", "modified", "owned"])
def test_navigation_transport_and_retirement(asset, case):
    subprocess.run(
        [
            "node",
            str(ROOT / "tests/js/navigation-runtime.cjs"),
            str(ROOT / "python_podcast/static/js" / asset),
            case,
        ],
        check=True,
        timeout=10,
    )
