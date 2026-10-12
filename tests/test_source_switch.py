"""Tests for the package source switch commands in commands.py.

``uv sync`` is always replaced, and every test works on a throwaway
``pyproject.toml`` below ``tmp_path``.
"""

from __future__ import annotations

import subprocess
import tomllib

import pytest
import typer

import commands

GIT_SOURCES = {
    "cast-vue": {"git": "https://github.com/ephes/cast-vue"},
    "cast-bootstrap5": {"git": "https://github.com/ephes/cast-bootstrap5"},
    "django-cast": {"git": "https://github.com/ephes/django-cast", "branch": "develop"},
    "django-indieweb": {"git": "https://github.com/ephes/django-indieweb", "branch": "develop"},
}
DEV_PACKAGES = ("cast-vue", "cast-bootstrap5", "django-cast", "django-indieweb")
DEV_SOURCES = {name: {"path": f"../{name}", "editable": True} for name in DEV_PACKAGES}

MULTILINE_PYPROJECT = """\
[project]
name = "example"  # keep this comment
dependencies = [
    "django-cast",
    "wagtail[extra]",  # brackets inside a string
]

[tool.uv.sources]
# sources used on this machine
cast-vue = { git = "https://github.com/ephes/cast-vue" }
django-cast = [
    { git = "https://github.com/ephes/django-cast", branch = "develop", marker = "sys_platform == 'linux'" },
    # a comment with a ] bracket and a "quote
    { path = "../django-cast#[x]", marker = "sys_platform != 'linux'" },
]
"django-indieweb" = { git = "https://example.invalid/fork", rev = "]}" }
weird = '''
django-cast = "inside a string"
]'''
other-package = { path = "../other-package" }

[tool.other]
matrix = [
    [1, 2],
    [3, 4]
]
text = \"\"\"
[tool.uv.sources]
django-cast = "not a real entry"
\"\"\"
"""


@pytest.fixture
def project(monkeypatch, tmp_path):
    root = tmp_path / "python-podcast"
    root.mkdir()
    for name in DEV_PACKAGES:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(commands, "get_project_root", lambda: root)
    return root


@pytest.fixture
def uv_sync(monkeypatch):
    calls = []

    def install(returncode=0, error=None):
        def run(cmd, **kwargs):
            calls.append((list(cmd), kwargs))
            if error is not None:
                raise error
            return subprocess.CompletedProcess(cmd, returncode)

        monkeypatch.setattr(commands.subprocess, "run", run)
        monkeypatch.setattr(commands.subprocess, "call", run)
        return calls

    return install


def write_pyproject(project, text=MULTILINE_PYPROJECT):
    path = project / "pyproject.toml"
    path.write_bytes(text.encode("utf-8"))
    return path


def without_sources(document):
    document = tomllib.loads(document) if isinstance(document, str) else document
    document["tool"]["uv"]["sources"] = {
        key: value for key, value in document["tool"]["uv"]["sources"].items() if key not in GIT_SOURCES
    }
    return document


def test_multiline_and_quoted_sources_survive_a_dev_to_git_round_trip(project, uv_sync):
    calls = uv_sync()
    path = write_pyproject(project)
    original = tomllib.loads(MULTILINE_PYPROJECT)

    commands.switch_to_dev_environment()

    dev_text = path.read_text(encoding="utf-8")
    dev = tomllib.loads(dev_text)
    assert {name: dev["tool"]["uv"]["sources"][name] for name in DEV_PACKAGES} == DEV_SOURCES
    assert without_sources(dev) == without_sources(original)

    commands.switch_to_git_sources()

    git_text = path.read_text(encoding="utf-8")
    git = tomllib.loads(git_text)
    assert {name: git["tool"]["uv"]["sources"][name] for name in GIT_SOURCES} == GIT_SOURCES
    assert without_sources(git) == without_sources(original)
    for text in (dev_text, git_text):
        # Unrelated tables, comments and the table's own comment are untouched.
        assert text.startswith(MULTILINE_PYPROJECT.split("[tool.uv.sources]")[0])
        assert text.endswith("[tool.other]" + MULTILINE_PYPROJECT.split("[tool.other]")[1])
        assert "# sources used on this machine\n" in text
        assert 'other-package = { path = "../other-package" }\n' in text
        assert '"django-indieweb" =' not in text
        assert text.count("\ndjango-indieweb = ") == 1
    assert [cmd for cmd, _ in calls] == [["uv", "sync"], ["uv", "sync", "--reinstall"]]
    assert all(not kwargs.get("shell") for _, kwargs in calls)


def test_multiline_inline_table_is_removed_completely():
    text = (
        "[tool.uv.sources]\n"
        "django-cast = {\n"
        '    git = "https://github.com/ephes/django-cast",  # } not the end\n'
        '    branch = "develop",\n'
        "}\n"
        'kept = { path = "../kept" }\n'
    )

    updated = commands._upsert_entries_in_table(text, "[tool.uv.sources]", {"django-cast": '{ path = "../x" }'})

    assert updated == '[tool.uv.sources]\nkept = { path = "../kept" }\ndjango-cast = { path = "../x" }\n'


def test_missing_table_and_missing_final_newline_are_handled(project, uv_sync):
    uv_sync()
    path = write_pyproject(project, '[project]\nname = "example"')

    commands.switch_to_git_sources()

    document = tomllib.loads(path.read_text(encoding="utf-8"))
    assert document == {"project": {"name": "example"}, "tool": {"uv": {"sources": GIT_SOURCES}}}


@pytest.mark.parametrize(
    "text",
    [
        '[tool.uv.sources]\ndjango-cast = { git = "https://example.invalid/x"\n',  # unterminated value
        '[tool.uv.sources]\ndjango-cast.git = "https://example.invalid/x"\n',  # dotted key cannot be replaced
        '[tool.uv.sources.django-cast]\ngit = "https://example.invalid/x"\n',  # sub-table cannot be replaced
        '[tool.uv]\nsources = "nonsense"\n',
        '[tool]\nuv = "nonsense"\n',
    ],
)
@pytest.mark.parametrize("command", ["switch_to_dev_environment", "switch_to_git_sources"])
def test_unsupported_or_malformed_input_leaves_the_original_bytes(project, uv_sync, capsys, command, text):
    calls = uv_sync()
    path = write_pyproject(project, text)

    with pytest.raises(typer.Exit) as excinfo:
        getattr(commands, command)()

    assert excinfo.value.exit_code == 1
    assert path.read_bytes() == text.encode("utf-8")
    assert sorted(entry.name for entry in project.iterdir()) == ["pyproject.toml"]
    assert calls == []
    output = capsys.readouterr().out
    assert "left unchanged" in " ".join(output.split())
    assert "activated" not in output and "Switched back" not in output


def test_windows_line_endings_are_preserved(project, uv_sync):
    uv_sync()
    text = '[tool.uv.sources]\r\ndjango-cast = [\r\n  { path = "../a" },\r\n]\r\n\r\n[tool.x]\r\ny = 1\r\n'
    path = write_pyproject(project, text)

    commands.switch_to_git_sources()

    updated = path.read_bytes().decode("utf-8")
    assert tomllib.loads(updated)["tool"]["uv"]["sources"] == GIT_SOURCES
    assert updated.endswith("\r\n\r\n[tool.x]\r\ny = 1\r\n")
    assert '{ path = "../a" }' not in updated


@pytest.mark.parametrize(
    ("command", "success_marker"),
    [("switch_to_dev_environment", "activated"), ("switch_to_git_sources", "Switched back")],
)
def test_failed_sync_fails_the_command_without_claiming_success(project, uv_sync, capsys, command, success_marker):
    calls = uv_sync(returncode=1)
    path = write_pyproject(project)

    with pytest.raises(typer.Exit) as excinfo:
        getattr(commands, command)()

    assert excinfo.value.exit_code == 1
    assert len(calls) == 1
    output = " ".join(capsys.readouterr().out.split())
    assert success_marker not in output
    assert "editable mode" not in output and "installed from their git" not in output
    assert "exited with status 1" in output
    assert "NOT updated" in output
    # The documented state after a failed sync: the new sources stay in pyproject.toml.
    sources = tomllib.loads(path.read_text(encoding="utf-8"))["tool"]["uv"]["sources"]
    expected = DEV_SOURCES if command == "switch_to_dev_environment" else GIT_SOURCES
    assert {name: sources[name] for name in expected} == expected
    assert "keeps the new source entries" in output


@pytest.mark.parametrize("command", ["switch_to_dev_environment", "switch_to_git_sources"])
def test_missing_uv_fails_the_command(project, uv_sync, capsys, command):
    uv_sync(error=FileNotFoundError("uv"))
    write_pyproject(project)

    with pytest.raises(typer.Exit) as excinfo:
        getattr(commands, command)()

    assert excinfo.value.exit_code == 1
    output = " ".join(capsys.readouterr().out.split())
    assert "could not be started" in output
    assert "activated" not in output and "Switched back" not in output


def test_successful_sync_reports_success(project, uv_sync, capsys):
    uv_sync()
    write_pyproject(project)

    commands.switch_to_dev_environment()
    commands.switch_to_git_sources()

    output = capsys.readouterr().out
    assert "Development environment activated!" in output
    assert "Switched back to git sources!" in output


def test_dev_switch_without_local_checkouts_changes_nothing(monkeypatch, tmp_path, uv_sync, capsys):
    root = tmp_path / "python-podcast"
    root.mkdir()
    monkeypatch.setattr(commands, "get_project_root", lambda: root)
    calls = uv_sync()
    path = write_pyproject(root)

    commands.switch_to_dev_environment()

    assert path.read_bytes() == MULTILINE_PYPROJECT.encode("utf-8")
    assert calls == []
    assert "activated" not in capsys.readouterr().out
