"""Cheap regression checks for the mobile performance asset cleanup."""

from pathlib import Path

from django.conf import settings

from scripts.minify_static import minified_assets

ROOT = Path(__file__).resolve().parents[1]


def test_committed_minified_assets_are_current():
    for target, expected in minified_assets().items():
        assert target.read_text() == expected, f"Run `just minify-static` after changing {target.name}"


def test_player_css_is_split_by_initial_visibility():
    static_css = ROOT / "python_podcast/static/css"
    template_css = ROOT / "python_podcast/templates/cast/_persistent_player_critical.min.css"
    critical = template_css.read_text()
    dock = (static_css / "persistent-player-dock.min.css").read_text()

    assert not (static_css / "persistent-player.min.css").exists()
    assert ".cast-play-card" in critical
    assert "position:fixed" not in critical
    assert ".cast-persistent{position:fixed" in dock
    assert ".cast-play-card{" not in dock


def test_show_note_styles_do_not_need_a_separate_request():
    assert not (ROOT / "python_podcast/static/css/show-notes.css").exists()
    for stylesheet in ("site-overrides.css", "pp/style.css"):
        content = (ROOT / "python_podcast/static/css" / stylesheet).read_text()
        assert ".show-note-icon" in content


def test_public_media_objects_receive_cache_control_metadata():
    cache_control = settings.AWS_S3_OBJECT_PARAMETERS["CacheControl"]
    assert "max-age=604800" in cache_control
    assert "s-maxage=604800" in cache_control
