"""Cheap regression checks for the mobile performance asset cleanup."""

from pathlib import Path

from django.conf import settings

from scripts.minify_static import minified_assets

ROOT = Path(__file__).resolve().parents[1]


def test_committed_minified_assets_are_current():
    for target, expected in minified_assets().items():
        assert target.read_text() == expected, f"Run `just minify-static` after changing {target.name}"


def test_show_note_styles_do_not_need_a_separate_request():
    assert not (ROOT / "python_podcast/static/css/show-notes.css").exists()
    for stylesheet in ("site-overrides.css", "pp/style.css"):
        content = (ROOT / "python_podcast/static/css" / stylesheet).read_text()
        assert ".show-note-icon" in content


def test_public_media_objects_receive_cache_control_metadata():
    cache_control = settings.AWS_S3_OBJECT_PARAMETERS["CacheControl"]
    assert "max-age=604800" in cache_control
    assert "s-maxage=604800" in cache_control
