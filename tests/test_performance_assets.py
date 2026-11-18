"""Cheap regression checks for the mobile performance asset cleanup."""

from pathlib import Path

import pytest
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


@pytest.mark.parametrize("operation", ["write", "backup", "replace", "replace-after"])
@pytest.mark.parametrize("failure_call", [1, 2, 3])
@pytest.mark.parametrize("failure_type", [OSError, KeyboardInterrupt, SystemExit])
def test_minifier_failure_preserves_previous_asset_set(tmp_path, monkeypatch, operation, failure_call, failure_type):
    import os

    from scripts import minify_static

    targets = {tmp_path / f"asset-{number}": f"new {number}\n" for number in range(3)}
    baseline = {target: f"old {number}\n" for number, target in enumerate(targets)}
    for target, content in baseline.items():
        target.write_text(content)
    monkeypatch.setattr(minify_static, "minified_assets", lambda: targets)
    monkeypatch.setattr(minify_static, "ROOT", tmp_path)
    calls = 0
    failure = failure_type("synthetic publication failure")
    original = {
        "write": Path.write_text,
        "backup": Path.write_bytes,
        "replace": os.replace,
        "replace-after": os.replace,
    }[operation]

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == failure_call:
            if operation == "replace-after":
                original(*args, **kwargs)
            raise failure
        return original(*args, **kwargs)

    if operation == "write":
        monkeypatch.setattr(Path, "write_text", fail)
    elif operation == "backup":
        monkeypatch.setattr(Path, "write_bytes", fail)
    else:
        monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(failure_type) as error:
        minify_static.main()
    assert error.value is failure
    assert {target: target.read_text() for target in targets} == baseline
    assert set(tmp_path.iterdir()) == set(targets)


def test_minifier_success_publishes_expected_set(tmp_path, monkeypatch):
    from scripts import minify_static

    targets = {tmp_path / f"asset-{number}": f"new {number}\n" for number in range(3)}
    monkeypatch.setattr(minify_static, "minified_assets", lambda: targets)
    monkeypatch.setattr(minify_static, "ROOT", tmp_path)
    minify_static.main()
    assert {target: target.read_text() for target in targets} == targets
    assert set(tmp_path.iterdir()) == set(targets)
    assert all(target.stat().st_mode & 0o444 == 0o444 for target in targets)


@pytest.mark.parametrize("failure_type", [OSError, KeyboardInterrupt, SystemExit])
def test_minifier_reports_retained_recovery_copy_if_compensation_fails(tmp_path, monkeypatch, failure_type):
    import os

    from scripts import minify_static

    targets = {tmp_path / f"asset-{number}": f"new {number}\n" for number in range(3)}
    for target in targets:
        target.write_text("previous\r\n", newline="")
    monkeypatch.setattr(minify_static, "minified_assets", lambda: targets)
    original = os.replace
    calls = 0
    failure = failure_type("synthetic publication failure")

    def fail(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise failure
        if calls == 4:
            raise failure_type("synthetic restore failure")
        return original(source, target)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(failure_type) as error:
        minify_static.main()
    assert error.value is failure
    retained = set(tmp_path.iterdir()) - set(targets)
    assert len(retained) == 1
    recovery = retained.pop()
    assert recovery.read_bytes() == b"previous\r\n"
    assert str(recovery) in " ".join(error.value.__notes__)


def test_minifier_cleanup_failure_does_not_hide_publication_interrupt(tmp_path, monkeypatch):
    from scripts import minify_static

    target = tmp_path / "asset"
    target.write_text("previous")
    monkeypatch.setattr(minify_static, "minified_assets", lambda: {target: "new"})
    failure = KeyboardInterrupt("synthetic staging interrupt")

    def interrupt_write(path, *args, **kwargs):
        raise failure

    original = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.parent == tmp_path:
            raise OSError("synthetic cleanup failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", interrupt_write)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(KeyboardInterrupt) as error:
        minify_static.main()
    assert error.value is failure
    assert "synthetic cleanup failure" in " ".join(error.value.__notes__)
    assert target.read_text() == "previous"
