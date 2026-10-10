"""Exercise deployment transactions with real Git repos, without SSH or hardware."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/dev_pi-deploy.py"


class Repositories:
    def __init__(self, directory):
        self.directory = directory
        self.origin = directory / "origin.git"
        self.source = directory / "source"
        self.device = directory / "device"
        self.command(directory, "init", "--bare", "--initial-branch=main", str(self.origin))
        self.command(directory, "clone", str(self.origin), str(self.source))
        self.command(self.source, "config", "user.name", "Deployment test")
        self.command(self.source, "config", "user.email", "test@example.invalid")
        self.write(self.source, "README.md", "base documentation\n")
        self.write(self.source, "web/index.html", "base page\n")
        self.write(self.source, ".gitignore", ".env\nweb/ignored.txt\n")
        self.command(self.source, "add", ".")
        self.command(self.source, "commit", "-m", "base")
        self.command(self.source, "push", "origin", "main")
        self.base = self.command(self.source, "rev-parse", "HEAD")
        self.command(directory, "clone", str(self.origin), str(self.device))
        self.command(self.source, "switch", "-c", "codex/change")
        self.write(self.device, ".env", "LOCAL_CONFIG=keep-me\n")

    @staticmethod
    def command(repo, *args):
        result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
        return result.stdout.strip()

    @staticmethod
    def write(repo, path, text):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def candidate(self, path="web/index.html", content="preview page\n"):
        self.write(self.source, path, content)
        self.command(self.source, "add", "--force", path)
        self.command(self.source, "commit", "-m", "candidate")
        target = self.command(self.source, "rev-parse", "HEAD")
        bundle = self.directory / f"{target}.bundle"
        self.command(self.source, "bundle", "create", str(bundle), f"{self.base}..HEAD")
        return target, bundle.read_bytes()

    def deploy(self, action, commit=None, bundle=b"", check=True):
        request = {
            "action": action,
            "repo": str(self.device),
            "base": self.base,
            "commit": commit,
            "restart_api": False,
        }
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT.read_text(), "_remote", json.dumps(request)],
            input=bundle,
            capture_output=True,
        )
        if check:
            assert result.returncode == 0, result.stderr.decode()
            return json.loads(result.stdout)
        assert result.returncode != 0
        return result.stderr.decode()

    def assert_base(self):
        assert self.command(self.device, "rev-parse", "HEAD") == self.base
        assert self.command(self.device, "branch", "--show-current") == "main"
        assert (self.device / ".env").read_text() == "LOCAL_CONFIG=keep-me\n"
        assert not (self.device / ".git/rider-preview.json").exists()


@pytest.fixture
def repos(tmp_path):
    return Repositories(tmp_path)


def test_preview_update_rollback_and_repeat_preserve_main_and_local_config(repos):
    commit, bundle = repos.candidate()
    result = repos.deploy("preview", commit, bundle)
    assert result["branch"] == f"rider-preview/{commit[:12]}"
    assert result["commit"] == commit
    assert result["dirty"] is False
    assert repos.command(repos.device, "rev-parse", "main") == repos.base
    assert (repos.device / "web/index.html").read_text() == "preview page\n"
    second, bundle = repos.candidate(content="second preview\n")
    repos.deploy("preview", second, bundle)
    repos.deploy("rollback")
    repos.assert_base()
    assert (repos.device / "web/index.html").read_text() == "base page\n"
    repos.deploy("preview", second, bundle)
    repos.deploy("rollback")
    repos.assert_base()


def test_release_accepts_reviewed_squash_with_identical_tree(repos):
    candidate, bundle = repos.candidate()
    repos.deploy("preview", candidate, bundle)
    repos.command(repos.source, "switch", "main")
    repos.command(repos.source, "merge", "--squash", candidate)
    repos.command(repos.source, "commit", "-m", "reviewed release")
    merged = repos.command(repos.source, "rev-parse", "HEAD")
    assert candidate != merged
    repos.command(repos.source, "push", "origin", "main")
    result = repos.deploy("release", merged)
    assert result["branch"] == "main"
    assert result["commit"] == merged
    assert result["preview"] is None
    assert result["previous"] == repos.base
    assert (repos.device / ".env").read_text() == "LOCAL_CONFIG=keep-me\n"


def test_release_without_preview_uses_expected_main(repos):
    repos.command(repos.source, "switch", "main")
    commit, _ = repos.candidate()
    repos.command(repos.source, "push", "origin", "main")
    result = repos.deploy("release", commit)
    assert result["commit"] == commit
    assert result["branch"] == "main"


def test_release_retry_after_api_failure_preserves_previous_revision(repos, monkeypatch):
    repos.command(repos.source, "switch", "main")
    commit, _ = repos.candidate()
    repos.command(repos.source, "push", "origin", "main")
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    globals_map = module["release"].__globals__
    monkeypatch.setitem(globals_map, "check_api_active", lambda: None)

    def failed_restart():
        raise RuntimeError("API health check failed")

    monkeypatch.setitem(globals_map, "restart_api", failed_restart)
    record_path = repos.device / ".git/rider-preview.json"
    request = {"commit": commit, "restart_api": True}
    with pytest.raises(RuntimeError, match="API health"):
        module["release"](repos.device, record_path, request)
    assert repos.command(repos.device, "rev-parse", "HEAD") == commit
    monkeypatch.setitem(globals_map, "restart_api", lambda: None)
    result = module["release"](repos.device, record_path, request)
    assert result["commit"] == commit
    saved = json.loads((repos.device / ".git/rider-last-release.json").read_text())
    assert saved == {"previous": repos.base, "commit": commit}


def test_dirty_device_is_rejected_without_discarding_changes(repos):
    commit, bundle = repos.candidate()
    repos.write(repos.device, "web/index.html", "device work\n")
    assert "local changes" in repos.deploy("preview", commit, bundle, check=False)
    assert (repos.device / "web/index.html").read_text() == "device work\n"
    repos.assert_base()


def test_ignored_file_collision_is_rejected(repos):
    commit, bundle = repos.candidate("web/ignored.txt", "candidate file\n")
    repos.write(repos.device, "web/ignored.txt", "existing device data\n")
    assert "overwrite a local file" in repos.deploy("preview", commit, bundle, check=False)
    assert (repos.device / "web/ignored.txt").read_text() == "existing device data\n"
    repos.assert_base()


@pytest.mark.parametrize(
    "path",
    [
        ".env.local",
        "evn.ssh.local",
        "config/local/settings.json",
        "docs_pl/_done/report.md",
        "systemd/rider-api.service",
        "scripts/sys_splash-info.py",
        "requirements.txt",
        "data/cache.db",
    ],
)
def test_protected_scope_is_rejected(repos, path):
    commit, bundle = repos.candidate(path, "private or separately deployed file\n")
    assert "protected path" in repos.deploy("preview", commit, bundle, check=False)
    repos.assert_base()


def test_invalid_python_is_rejected_before_checkout(repos):
    commit, bundle = repos.candidate("apps/example.py", "def :\n")
    assert "invalid syntax" in repos.deploy("preview", commit, bundle, check=False)
    repos.assert_base()


def test_bundle_must_match_requested_commit(repos):
    _, bundle = repos.candidate()
    assert "Bundle HEAD" in repos.deploy("preview", repos.base, bundle, check=False)
    repos.assert_base()


def test_review_changes_must_be_previewed_again(repos):
    candidate, bundle = repos.candidate()
    repos.deploy("preview", candidate, bundle)
    repos.command(repos.source, "switch", "main")
    reviewed, _ = repos.candidate(content="different reviewed page\n")
    repos.command(repos.source, "push", "origin", "main")
    assert "differs from the tested preview" in repos.deploy("release", reviewed, check=False)
    assert repos.command(repos.device, "rev-parse", "HEAD") == candidate
    assert (repos.device / ".git/rider-preview.json").exists()


def test_wrong_release_commit_is_rejected(repos):
    assert "expected merged commit" in repos.deploy("release", "0" * 40, check=False)
    repos.assert_base()


def test_wrong_base_is_rejected(repos):
    candidate, bundle = repos.candidate()
    repos.base = "0" * 40
    assert "local base commit" in repos.deploy("preview", candidate, bundle, check=False)
    assert repos.command(repos.device, "branch", "--show-current") == "main"


def test_deployment_lock_is_not_removed_by_another_run(repos):
    lock = repos.device / ".git/rider-deploy.lock"
    lock.write_text("other operation")
    assert "rider-deploy.lock" in repos.deploy("rollback", check=False)
    assert lock.read_text() == "other operation"
    repos.assert_base()


def test_rollback_preserves_unexpected_checkout(repos):
    commit, bundle = repos.candidate()
    repos.deploy("preview", commit, bundle)
    repos.command(repos.device, "switch", "--detach", commit)
    assert "no longer matches" in repos.deploy("rollback", check=False)
    assert repos.command(repos.device, "rev-parse", "HEAD") == commit
    assert repos.command(repos.device, "branch", "--show-current") == ""


def test_secret_removed_from_final_tree_is_rejected_before_ssh(repos, monkeypatch):
    repos.candidate(".env.local", "do-not-transfer-this-history\n")
    repos.command(repos.source, "rm", ".env.local")
    repos.command(repos.source, "commit", "-m", "remove local configuration")
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    globals_map = module["main"].__globals__
    monkeypatch.setitem(globals_map, "ROOT", repos.source)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "preview", "--base", repos.base])

    def forbidden_ssh(*args):
        raise AssertionError("Private history must be rejected before transport")

    monkeypatch.setitem(globals_map, "ssh", forbidden_ssh)
    with pytest.raises(RuntimeError, match="protected path"):
        module["main"]()
