"""Settings for Playwright end-to-end verification of the custom audio player.

Reuses the test settings but pins the custom audio player, defines the Django
Vite config (normally only in local.py) against the built static manifests, and
drops the legacy database so the live-server test only needs one database.
"""

from pathlib import Path

import cast
import cast_bootstrap5
import cast_vue

from .test import *  # noqa

# Use the custom web-component audio player for this verification.
CAST_AUDIO_PLAYER = "custom"

# The persistent-player staging proof is toggled per-test via the pytest
# `settings` fixture (see tests/e2e/test_persistent_player.py); leave it at the
# base default (False) here so the page-local custom-player test still applies.

# Single database for the live-server test (drop the legacy connection).
DATABASES = {"default": DATABASES["default"]}  # noqa: F405
DATABASES["default"]["ATOMIC_REQUESTS"] = False

# Django Vite — serve the built assets from each package's static manifest.
DJANGO_VITE_ASSETS_PATH = "unused"
DJANGO_VITE_DEV_MODE = False


def _package_manifest_path(package, *path_parts: str) -> Path:
    return Path(package.__file__).resolve().parent.joinpath("static", *path_parts, "manifest.json")


DJANGO_VITE = {
    "cast_vue": {
        "dev_mode": False,
        "static_url_prefix": "cast_vue/",
        "manifest_path": _package_manifest_path(cast_vue, "cast_vue"),
    },
    "cast-bootstrap5": {
        "dev_mode": False,
        "static_url_prefix": "cast_bootstrap5/vite/",
        "manifest_path": _package_manifest_path(cast_bootstrap5, "cast_bootstrap5", "vite"),
    },
    "cast": {
        "dev_mode": False,
        "static_url_prefix": "cast/vite/",
        "manifest_path": _package_manifest_path(cast, "cast", "vite"),
    },
}
