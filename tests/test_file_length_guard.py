"""File-size policy tests use temporary text files, never robot hardware."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/dev_check-file-length.py"
spec = importlib.util.spec_from_file_location("file_length_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize(
    "lines,exit_code,label", [(600, 0, None), (601, 0, "WARNING"), (800, 0, "WARNING"), (801, 1, "ERROR")]
)
def test_threshold_boundaries(tmp_path, capsys, lines, exit_code, label):
    file = tmp_path / "sample.py"
    file.write_text("# line\n" * lines)
    assert guard.check_files([file], root=tmp_path) == exit_code
    output = capsys.readouterr().out
    if label:
        assert f"{label}: sample.py: {lines} lines" in output
    else:
        assert "WARNING:" not in output and "ERROR:" not in output


def test_warning_uses_github_annotation_and_still_passes(tmp_path, capsys):
    file = tmp_path / "sample.py"
    file.write_text("\n" * 700)
    assert guard.check_files([file], root=tmp_path, annotations=True) == 0
    assert "::warning file=sample.py,line=1::700 lines" in capsys.readouterr().out


def test_error_annotation_escapes_filename(tmp_path, capsys):
    file = tmp_path / "sample%,:\n.py"
    file.write_text("\n" * 801)
    assert guard.check_files([file], root=tmp_path, annotations=True) == 1
    assert "file=sample%25%2C%3A%0A.py" in capsys.readouterr().out


def test_missing_file_fails_instead_of_silently_skipping(tmp_path, capsys):
    assert guard.check_files([tmp_path / "missing.py"], root=tmp_path) == 1
    assert "cannot inspect" in capsys.readouterr().out


def test_changed_files_use_null_delimiters_and_exclude_deletions(tmp_path, monkeypatch):
    def run(args, **kwargs):
        assert args == ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z", "base", "head", "--", "*.py"]
        assert kwargs["cwd"] == tmp_path and kwargs["check"]
        return SimpleNamespace(stdout=b"tests/test one.py\0apps/module.py\0")

    monkeypatch.setattr(guard.subprocess, "run", run)
    assert guard.changed_files(tmp_path, "base", "head") == [
        tmp_path / "tests/test one.py",
        tmp_path / "apps/module.py",
    ]


def test_cli_and_hook_share_policy_without_environment_opt_in(tmp_path, monkeypatch):
    file = tmp_path / "sample.py"
    file.write_text("\n" * 801)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("ENFORCE_FILE_LENGTH", raising=False)
    assert guard.main([str(file)]) == 1
    file.write_text("\n" * 800)
    assert guard.main([str(file)]) == 0


def test_cli_git_failure_fails_closed(monkeypatch):
    def fail(*_):
        raise subprocess.CalledProcessError(128, "git", stderr=b"unknown ref")

    monkeypatch.setattr(guard, "changed_files", fail)
    assert guard.main(["--base", "missing", "--head", "HEAD"]) == 1
