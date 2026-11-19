"""Cheap regression checks for the mobile performance asset cleanup."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from django.conf import settings

from scripts.minify_static import DOCK_MARKER, minified_assets

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


@pytest.fixture
def asset_dir(tmp_path, monkeypatch):
    from scripts import minify_static

    monkeypatch.setattr(minify_static, "ROOT", tmp_path)
    directory = tmp_path / "assets"
    directory.mkdir()
    return directory


@pytest.mark.parametrize("operation", ["write", "backup", "replace", "replace-after"])
@pytest.mark.parametrize("failure_call", [1, 2, 3])
@pytest.mark.parametrize("failure_type", [OSError, KeyboardInterrupt, SystemExit])
def test_minifier_failure_preserves_previous_asset_set(asset_dir, monkeypatch, operation, failure_call, failure_type):
    import os

    from scripts import minify_static

    targets = {asset_dir / f"asset-{number}": f"new {number}\n" for number in range(3)}
    baseline = {target: f"old {number}\n" for number, target in enumerate(targets)}
    for target, content in baseline.items():
        target.write_text(content)
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: tuple(targets))
    monkeypatch.setattr(minify_static, "minified_assets", lambda: targets)
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
    assert set(asset_dir.iterdir()) == set(targets)


def test_minifier_success_publishes_expected_set(asset_dir, monkeypatch):
    from scripts import minify_static

    targets = {asset_dir / f"asset-{number}": f"new {number}\n" for number in range(3)}
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: tuple(targets))
    monkeypatch.setattr(minify_static, "minified_assets", lambda: targets)
    minify_static.main()
    assert {target: target.read_text() for target in targets} == targets
    assert set(asset_dir.iterdir()) == set(targets)
    assert all(target.stat().st_mode & 0o444 == 0o444 for target in targets)


@pytest.mark.parametrize("failure_type", [OSError, KeyboardInterrupt, SystemExit])
def test_minifier_reports_retained_recovery_copy_if_compensation_fails(asset_dir, monkeypatch, failure_type):
    import os

    from scripts import minify_static

    targets = {asset_dir / f"asset-{number}": f"new {number}\n" for number in range(3)}
    for target in targets:
        target.write_text("previous\r\n", newline="")
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: tuple(targets))
    monkeypatch.setattr(minify_static, "minified_assets", lambda: targets)
    original = os.replace
    calls = 0
    failure = failure_type("synthetic publication failure")

    def fail(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise failure
        if calls == 3:
            raise failure_type("synthetic restore failure")
        return original(source, target)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(failure_type) as error:
        minify_static.main()
    assert error.value is failure
    (recovery,) = asset_dir.glob(".asset-0.*/backup")
    assert recovery.read_bytes() == b"previous\r\n"
    assert str(recovery) in " ".join(error.value.__notes__)

    monkeypatch.setattr(os, "replace", original)
    with monkeypatch.context() as restart:

        def fail_generation():
            raise RuntimeError("synthetic minifier failure")

        restart.setattr(minify_static, "minified_assets", fail_generation)
        with pytest.raises(RuntimeError, match="synthetic minifier failure"):
            minify_static.main()
    assert all(target.read_bytes() == b"previous\r\n" for target in targets)
    assert set(asset_dir.iterdir()) == set(targets)


def test_minifier_cleanup_failure_does_not_hide_publication_interrupt(asset_dir, monkeypatch):
    from scripts import minify_static

    target = asset_dir / "asset"
    target.write_text("previous")
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: (target,))
    monkeypatch.setattr(minify_static, "minified_assets", lambda: {target: "new"})
    failure = KeyboardInterrupt("synthetic staging interrupt")

    def interrupt_write(path, *args, **kwargs):
        raise failure

    original = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.parent.parent == asset_dir:
            raise OSError("synthetic cleanup failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", interrupt_write)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(KeyboardInterrupt) as error:
        minify_static.main()
    assert error.value is failure
    assert "synthetic cleanup failure" in " ".join(error.value.__notes__)
    assert target.read_text() == "previous"


@pytest.mark.parametrize("pause_at", [2, 3, "kill", "kill-new"], ids=["publish", "restore", "kill", "kill-new"])
def test_minifier_excludes_other_process_until_recovery(tmp_path, pause_at):
    css = tmp_path / "python_podcast/static/css/persistent-player.css"
    js = tmp_path / "python_podcast/static/js/persistent-player.js"
    critical = tmp_path / "python_podcast/templates/cast/_persistent_player_critical.min.css"
    dock = css.with_name("persistent-player-dock.min.css")
    player = js.with_suffix(".min.js")
    targets = (critical, dock, player)
    for path in (*targets, css, js):
        path.parent.mkdir(parents=True, exist_ok=True)

    def write_sources(color):
        css.write_text(f".play {{ color: {color}; }}\n{DOCK_MARKER} */\n.dock {{ color: {color}; }}")
        js.write_text(f"const color = '{color}';\n")

    worker = """
import sys
from pathlib import Path
from scripts import minify_static as minifier

root, role, pause_at = sys.argv[1:]
minifier.ROOT = root = Path(root)
minifier.PERSISTENT_CSS = root / "python_podcast/static/css/persistent-player.css"
minifier.PERSISTENT_JS = root / "python_podcast/static/js/persistent-player.js"
generate = minifier.minified_assets

def tracked_generation():
    (root / f"{role}.captured").touch()
    if role == "failing":
        raise RuntimeError("synthetic minifier failure")
    return generate()

minifier.minified_assets = tracked_generation
if role == "interrupted":
    original = minifier.os.replace
    calls = 0

    def replace(source, target):
        global calls
        calls += 1
        if pause_at.startswith("kill") and calls == 1:
            original(source, target)
            (root / "ready").touch()
            sys.stdin.readline()
            return
        if not pause_at.startswith("kill") and calls == int(pause_at):
            (root / "ready").touch()
            sys.stdin.readline()
        if calls == 2:
            raise KeyboardInterrupt("synthetic publication interrupt")
        return original(source, target)

    minifier.os.replace = replace
minifier.main()
"""

    def command(role):
        return [sys.executable, "-c", worker, str(tmp_path), role, str(pause_at)]

    write_sources("red")
    subprocess.run(command("baseline"), cwd=ROOT, check=True, capture_output=True, timeout=15)
    killed = isinstance(pause_at, str)
    if pause_at == "kill-new":
        critical.unlink()
    previous = tuple(path.read_bytes() if path.exists() else None for path in targets)
    write_sources("green")
    with subprocess.Popen(
        command("interrupted"), cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as first:
        try:
            deadline = time.monotonic() + 15
            while not (tmp_path / "ready").exists():
                if first.poll() is not None:
                    pytest.fail(first.stderr.read().decode())
                if time.monotonic() >= deadline:
                    pytest.fail("minifier did not reach the replace barrier")
                time.sleep(0.01)
            assert critical.read_text() == ".play{color:green}\n"
            write_sources("blue")
            competing = subprocess.run(command("competing"), cwd=ROOT, capture_output=True, timeout=15)
            captured_while_busy = (tmp_path / "competing.captured").exists()
            if killed:
                first.kill()
            _, error = first.communicate(input=None if killed else b"\n", timeout=15)
        finally:
            if first.poll() is None:
                first.kill()

    assert first.returncode != 0
    if killed:
        restart = subprocess.run(command("failing"), cwd=ROOT, capture_output=True, timeout=15)
        assert restart.returncode != 0
        assert b"RuntimeError: synthetic minifier failure" in restart.stderr
    else:
        assert b"KeyboardInterrupt: synthetic publication interrupt" in error
    assert competing.returncode != 0, "second writer ran while the first still owned publication"
    assert b"already running" in competing.stderr
    assert not captured_while_busy
    assert tuple(path.read_bytes() if path.exists() else None for path in targets) == previous
    assert all(not list(path.parent.glob(f".{path.name}.*")) for path in targets)
    assert not (tmp_path / ".minify-static-transaction").exists()

    subprocess.run(command("competing"), cwd=ROOT, check=True, capture_output=True, timeout=15)
    assert tuple(path.read_text() for path in targets) == (
        ".play{color:blue}\n",
        ".dock{color:blue}\n",
        "const color='blue';\n",
    )
    assert all(not list(path.parent.glob(f".{path.name}.*")) for path in targets)
