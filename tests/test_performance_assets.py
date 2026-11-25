"""Cheap regression checks for the mobile performance asset cleanup."""

import errno
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
    import shutil

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
        "backup": shutil.copyfileobj,
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
        monkeypatch.setattr(shutil, "copyfileobj", fail)
    else:
        monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(failure_type) as error:
        minify_static.main()
    assert error.value is failure
    assert {target: target.read_text() for target in targets} == baseline
    assert set(asset_dir.iterdir()) == set(targets)


@pytest.mark.parametrize("truncated", [False, True])
def test_minifier_backs_up_large_assets_in_chunks_and_restores_mode(asset_dir, monkeypatch, truncated):
    import os
    from contextlib import contextmanager
    from types import SimpleNamespace

    from scripts import minify_static

    target = asset_dir / "large"
    original = b"\x00binary asset\xff" * (128 * 1024)
    target.write_bytes(original)
    target.chmod(0o640)
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: (target,))
    monkeypatch.setattr(minify_static, "minified_assets", lambda: {target: "replacement"})
    open_path = Path.open
    replace = os.replace
    read_sizes = []

    @contextmanager
    def track_reads(path, *args, **kwargs):
        with open_path(path, *args, **kwargs) as stream:
            if path != target:
                yield stream
                return

            def read(size=-1):
                assert 0 < size <= 1024 * 1024, "backup issued an unbounded read"
                read_sizes.append(size)
                if truncated and len(read_sizes) == 2:
                    return b""
                return stream.read(size)

            yield SimpleNamespace(read=read)

    def fail_after_publish(source, destination):
        assert not truncated, "incomplete backup allowed publication"
        replace(source, destination)
        if source.name == "candidate":
            raise OSError("synthetic interruption after replacement")

    with monkeypatch.context() as tracked:
        tracked.setattr(Path, "open", track_reads)
        tracked.setattr(os, "replace", fail_after_publish)
        failure = "Asset changed size" if truncated else "synthetic interruption"
        with pytest.raises(OSError, match=failure):
            minify_static.main()
    assert len(read_sizes) >= 2
    assert target.read_bytes() == original
    assert target.stat().st_mode & 0o777 == 0o640
    assert set(asset_dir.iterdir()) == {target}
    assert not (asset_dir.parent / ".minify-static-transaction").exists()


def test_minifier_success_publishes_expected_set(asset_dir, monkeypatch):
    from scripts import minify_static

    targets = {asset_dir / f"asset-{number}": f"new {number}\n" for number in range(3)}
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: tuple(targets))
    monkeypatch.setattr(minify_static, "minified_assets", lambda: targets)
    minify_static.main()
    assert {target: target.read_text() for target in targets} == targets
    assert set(asset_dir.iterdir()) == set(targets)
    assert all(target.stat().st_mode & 0o444 == 0o444 for target in targets)


def test_minifier_syncs_staged_journal_before_any_replacement(asset_dir, monkeypatch):
    import os

    from scripts import minify_static

    existing = asset_dir / "existing"
    existing.write_text("previous")
    absent = asset_dir / "absent"
    targets = (existing, absent)
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: targets)
    monkeypatch.setattr(minify_static, "minified_assets", lambda: dict.fromkeys(targets, "new"))
    flush = minify_static._flush
    replace = os.replace
    synced = set()
    replaced = []

    def track_sync(fd):
        flush(fd)
        info = os.fstat(fd)
        synced.add((info.st_dev, info.st_ino))

    def check_replace(source, target):
        if source.name == "candidate":
            journal = asset_dir.parent / ".minify-static-transaction"
            (transaction,) = journal.iterdir()
            existing_scratch = minify_static._scratch(existing, transaction)
            absent_scratch = minify_static._scratch(absent, transaction)
            paths = [
                journal.parent,
                journal,
                transaction,
                transaction / "pending",
                asset_dir,
                existing_scratch,
                existing_scratch / "backup",
                absent_scratch,
                absent_scratch / "absent",
            ]
            next_target = len(replaced)
            remaining = targets[next_target:]
            paths.extend(minify_static._scratch(path, transaction) / "candidate" for path in remaining)
            for path in paths:
                info = path.stat()
                assert (info.st_dev, info.st_ino) in synced, f"{path} was not synced before replacing {target}"
            replaced.append(target)
        replace(source, target)

    monkeypatch.setattr(minify_static, "_flush", track_sync)
    monkeypatch.setattr(os, "replace", check_replace)
    minify_static.main()
    assert tuple(replaced) == targets


@pytest.mark.parametrize("full_fsync_error", [None, OSError(errno.ENOTSUP, "unsupported")])
def test_minifier_sync_prefers_full_fsync(tmp_path, monkeypatch, full_fsync_error):
    import fcntl
    import os

    from scripts import minify_static

    calls = []

    def fake_fcntl(fd, command, *args):
        calls.append(("fcntl", command))
        if full_fsync_error is not None:
            raise full_fsync_error
        return 0

    monkeypatch.setattr(fcntl, "F_FULLFSYNC", 51, raising=False)
    monkeypatch.setattr(fcntl, "fcntl", fake_fcntl)
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(("fsync", None)))
    minify_static._sync(tmp_path)
    expected = [("fcntl", 51)] if full_fsync_error is None else [("fcntl", 51), ("fsync", None)]
    assert calls == expected


def test_minifier_sync_propagates_full_fsync_write_error(tmp_path, monkeypatch):
    import fcntl
    import os

    from scripts import minify_static

    calls = []

    def failing_fcntl(fd, command, *args):
        raise OSError(errno.EIO, "synthetic write-back failure")

    monkeypatch.setattr(fcntl, "F_FULLFSYNC", 51, raising=False)
    monkeypatch.setattr(fcntl, "fcntl", failing_fcntl)
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append("fsync"))
    with pytest.raises(OSError, match="write-back failure"):
        minify_static._sync(tmp_path)
    assert calls == []


def test_minifier_rolls_back_when_pending_retirement_fails(asset_dir, monkeypatch):
    from scripts import minify_static

    target = asset_dir / "asset"
    target.write_text("previous")
    journal = asset_dir.parent / ".minify-static-transaction"
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: (target,))
    monkeypatch.setattr(minify_static, "minified_assets", lambda: {target: "new"})
    unlink = Path.unlink
    interrupted = []

    def interrupt_first_pending_unlink(path, *args, **kwargs):
        if path.name == "pending" and not interrupted:
            interrupted.append(path)
            raise KeyboardInterrupt
        unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupt_first_pending_unlink)
    with pytest.raises(KeyboardInterrupt) as error:
        minify_static.main()
    # The in-process recovery rolled back the generation and retired the journal.
    assert not getattr(error.value, "__notes__", ())
    assert interrupted
    assert target.read_text() == "previous"
    assert not journal.exists()
    assert set(asset_dir.iterdir()) == {target}


def test_minifier_sync_uses_fsync_without_full_fsync(tmp_path, monkeypatch):
    import fcntl
    import os

    from scripts import minify_static

    calls = []
    monkeypatch.delattr(fcntl, "F_FULLFSYNC", raising=False)
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append("fsync"))
    minify_static._sync(tmp_path)
    assert calls == ["fsync"]


@pytest.mark.parametrize("fail_retirement", [False, True])
def test_minifier_syncs_published_outputs_before_retiring_journal(asset_dir, monkeypatch, fail_retirement):
    import os

    from scripts import minify_static

    target = asset_dir / "asset"
    target.write_text("previous")
    journal = asset_dir.parent / ".minify-static-transaction"
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: (target,))
    monkeypatch.setattr(minify_static, "minified_assets", lambda: {target: "new"})
    sync = minify_static._sync
    unlink = Path.unlink
    replace = os.replace
    events = []

    def track_sync(path):
        events.append(("sync", path))
        if fail_retirement and path.parent == journal and not (path / "pending").exists():
            raise OSError("synthetic journal retirement sync failure")
        sync(path)

    def track_unlink(path, *args, **kwargs):
        events.append(("unlink", path))
        unlink(path, *args, **kwargs)

    def track_replace(source, destination):
        replace(source, destination)
        events.append(("replace", destination))

    monkeypatch.setattr(minify_static, "_sync", track_sync)
    monkeypatch.setattr(Path, "unlink", track_unlink)
    monkeypatch.setattr(os, "replace", track_replace)
    if fail_retirement:
        with pytest.raises(OSError, match="journal retirement sync failure"):
            minify_static.main()
    else:
        minify_static.main()

    [(retirement, pending)] = [
        (index, path)
        for index, (operation, path) in enumerate(events)
        if operation == "unlink" and path.name == "pending"
    ]
    start, end = retirement - 3, retirement + 2
    assert events[start:end] == [
        ("replace", target),
        ("sync", target),
        ("sync", target.parent),
        ("unlink", pending),
        ("sync", pending.parent),
    ]
    assert target.read_text() == "new"
    if fail_retirement:
        backup = minify_static._scratch(target, pending.parent) / "backup"
        assert backup.read_text() == "previous"
        monkeypatch.setattr(minify_static, "_sync", sync)

        def stop_after_recovery():
            raise RuntimeError("stop after recovery")

        monkeypatch.setattr(minify_static, "minified_assets", stop_after_recovery)
        with pytest.raises(RuntimeError, match="stop after recovery"):
            minify_static.main()
        assert target.read_text() == "new"
    assert set(asset_dir.iterdir()) == {target}
    assert not journal.exists()


def test_minifier_retries_rollback_after_output_parent_sync_fails(asset_dir, monkeypatch):
    import os

    from scripts import minify_static

    existing = asset_dir / "existing"
    existing.write_text("previous")
    absent_parent = asset_dir.parent / "other-assets"
    absent_parent.mkdir()
    absent = absent_parent / "absent"
    targets = (existing, absent)
    journal = asset_dir.parent / ".minify-static-transaction"
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: targets)
    monkeypatch.setattr(minify_static, "minified_assets", lambda: dict.fromkeys(targets, "new"))
    replace = os.replace
    sync = minify_static._sync
    rolling_back = False
    parent_syncs = []

    def fail_publication(source, target):
        nonlocal rolling_back
        replace(source, target)
        if source.name == "candidate" and target == existing:
            # A power loss can leave both names visible after a cross-directory rename.
            source.write_text("new")
        if source.name == "candidate" and target == absent:
            rolling_back = True
            raise OSError("synthetic publication failure")

    def fail_first_rollback_parent_sync(path):
        if rolling_back and path in (absent_parent, asset_dir):
            parent_syncs.append(path)
            if path == asset_dir and parent_syncs.count(path) == 1:
                raise OSError("synthetic rollback sync failure")
        sync(path)

    monkeypatch.setattr(os, "replace", fail_publication)
    monkeypatch.setattr(minify_static, "_sync", fail_first_rollback_parent_sync)
    with pytest.raises(OSError, match="publication failure") as error:
        minify_static.main()
    assert "synthetic rollback sync failure" in " ".join(getattr(error.value, "__notes__", ()))
    (transaction,) = journal.iterdir()
    assert (transaction / "pending").exists()
    assert (minify_static._scratch(existing, transaction) / "backup").read_text() == "previous"
    assert (minify_static._scratch(absent, transaction) / "absent").exists()

    def stop_after_recovery():
        raise RuntimeError("stop after recovery")

    monkeypatch.setattr(minify_static, "minified_assets", stop_after_recovery)
    with pytest.raises(RuntimeError, match="stop after recovery"):
        minify_static.main()
    assert parent_syncs[:4] == [absent_parent, asset_dir, absent_parent, asset_dir]
    assert existing.read_text() == "previous"
    assert not journal.exists()
    assert set(asset_dir.iterdir()) == {existing}
    assert list(absent_parent.iterdir()) == []


def test_minifier_rejects_symlink_without_reading_referent(asset_dir, monkeypatch):
    from scripts import minify_static

    normal = [asset_dir / "first", asset_dir / "second"]
    for path in normal:
        path.write_bytes(b"previous")
    original_inodes = [path.stat().st_ino for path in normal]
    referent = asset_dir.parent / "referent"
    referent.write_bytes(b"referent")
    link = asset_dir / "linked"
    link.symlink_to(referent)
    targets = (*normal, link)
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: targets)
    monkeypatch.setattr(minify_static, "minified_assets", lambda: dict.fromkeys(targets, "new"))
    read_bytes = Path.read_bytes

    def guard(path):
        assert path not in (link, referent), "minifier read the link referent"
        return read_bytes(path)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_bytes", guard)
        with pytest.raises(RuntimeError, match="linked"):
            minify_static.main()
    assert link.readlink() == referent
    assert referent.read_bytes() == b"referent"
    assert [path.stat().st_ino for path in normal] == original_inodes
    assert all(path.read_bytes() == b"previous" for path in normal)
    assert set(asset_dir.iterdir()) == set(targets)
    assert not (asset_dir.parent / ".minify-static-transaction").exists()


def test_minifier_lists_all_unsupported_outputs(asset_dir, monkeypatch):
    from scripts import minify_static

    broken = asset_dir / "broken"
    broken.symlink_to(asset_dir / "missing")
    directory = asset_dir / "directory"
    directory.mkdir()
    referent = asset_dir.parent / "referent"
    referent.write_bytes(b"referent")
    hardlink = asset_dir / "hardlink"
    hardlink.hardlink_to(referent)
    targets = (broken, directory, hardlink)
    monkeypatch.setattr(minify_static, "_asset_targets", lambda: targets)
    monkeypatch.setattr(minify_static, "minified_assets", lambda: dict.fromkeys(targets, "new"))

    with pytest.raises(RuntimeError) as error:
        minify_static.main()
    assert set(str(error.value).splitlines()[1:]) == {str(target.relative_to(asset_dir.parent)) for target in targets}
    assert broken.is_symlink()
    assert directory.is_dir()
    assert hardlink.samefile(referent)


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
    failure = failure_type("synthetic publication failure")
    first, second, _ = targets

    def fail(source, target):
        if source.name == "candidate" and target == second:
            raise failure
        if source.name == "restore" and target == first:
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
