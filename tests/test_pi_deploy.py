"""Exercise deployment transactions with real Git repos, without SSH or hardware."""

import io
import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/dev_pi-deploy.py"


class Repositories:
    def __init__(self, directory):
        """Create isolated source, origin and device repositories with local config."""
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
        """Run Git and return its output for fixture setup and assertions."""
        result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
        return result.stdout.strip()

    @staticmethod
    def write(repo, path, text):
        """Write fixture content after creating its parent directories."""
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def candidate(self, path="web/index.html", content="preview page\n"):
        """Commit a candidate and bundle its history relative to the fixture base."""
        self.write(self.source, path, content)
        self.command(self.source, "add", "--force", path)
        self.command(self.source, "commit", "-m", "candidate")
        target = self.command(self.source, "rev-parse", "HEAD")
        bundle = self.directory / f"{target}.bundle"
        self.command(self.source, "bundle", "create", str(bundle), f"{self.base}..HEAD")
        return target, bundle.read_bytes()

    def deploy(self, action, commit=None, bundle=b"", check=True):
        """Run the exact transmitted helper source as a separate device process."""
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
        """Verify rollback preserved main, private config and record cleanup."""
        assert self.command(self.device, "rev-parse", "HEAD") == self.base
        assert self.command(self.device, "branch", "--show-current") == "main"
        assert (self.device / ".env").read_text() == "LOCAL_CONFIG=keep-me\n"
        assert not (self.device / ".git/rider-preview.json").exists()


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """Provide independent real Git repositories for each deployment test."""
    monkeypatch.setenv("RIDER_TEST_GIT_ROOT", str(tmp_path))
    return Repositories(tmp_path)


def test_preview_update_rollback_and_repeat_preserve_main_and_local_config(repos):
    """Exercise repeated previews and rollback without losing local configuration."""
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
    """Accept a reviewed squash whose file tree matches the tested preview."""
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


def test_preview_inherits_api_restart_and_rollback_restores_running_revision(repos, monkeypatch):
    """Keep API restart intent through subsequent previews and rollback."""
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    globals_map = module["preview"].__globals__
    calls = []
    monkeypatch.setitem(globals_map, "check_api_active", lambda: calls.append("active"))
    monkeypatch.setitem(globals_map, "restart_api", lambda: calls.append("restart"))
    record_path = repos.device / ".git/rider-preview.json"
    request = {"base": repos.base, "restart_api": True}
    for restart, content in [(True, "first API\n"), (False, "next API\n")]:
        commit, bundle = repos.candidate(content=content)
        request.update(commit=commit, restart_api=restart)
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(bundle)))
        result = module["preview"](repos.device, record_path, request)
        assert result["preview"]["restart_api"] is True
    module["rollback"](repos.device, record_path)
    assert calls == ["active", "restart", "active", "restart", "restart"]
    repos.assert_base()


def test_inherited_api_restart_checks_service_before_checkout(repos, monkeypatch):
    """Reject inherited restart when the API stopped, preserving the current preview."""
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    globals_map = module["preview"].__globals__
    monkeypatch.setitem(globals_map, "check_api_active", lambda: None)
    monkeypatch.setitem(globals_map, "restart_api", lambda: None)
    first, bundle = repos.candidate()
    record_path = repos.device / ".git/rider-preview.json"
    request = {"base": repos.base, "commit": first, "restart_api": True}
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(bundle)))
    module["preview"](repos.device, record_path, request)
    second, bundle = repos.candidate(content="next API\n")
    request.update(commit=second, restart_api=False)

    def inactive_api():
        """Simulate an API preflight failure without invoking systemd."""
        raise RuntimeError("API is not active")

    monkeypatch.setitem(globals_map, "check_api_active", inactive_api)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(bundle)))
    with pytest.raises(RuntimeError, match="API is not active"):
        module["preview"](repos.device, record_path, request)
    assert repos.command(repos.device, "rev-parse", "HEAD") == first
    assert json.loads(record_path.read_text())["commit"] == first


def test_release_without_preview_uses_expected_main(repos):
    """Release reviewed main directly from an unchanged device base."""
    repos.command(repos.source, "switch", "main")
    commit, _ = repos.candidate()
    repos.command(repos.source, "push", "origin", "main")
    result = repos.deploy("release", commit)
    assert result["commit"] == commit
    assert result["branch"] == "main"


def test_release_retry_after_api_failure_preserves_previous_revision(repos, monkeypatch):
    """Retain the recovery revision when an API health failure is retried."""
    repos.command(repos.source, "switch", "main")
    commit, _ = repos.candidate()
    repos.command(repos.source, "push", "origin", "main")
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    globals_map = module["release"].__globals__
    monkeypatch.setitem(globals_map, "check_api_active", lambda: None)

    def failed_restart():
        """Simulate failure after the release checkout has been updated."""
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
    """Preserve device edits when its checkout is not clean."""
    commit, bundle = repos.candidate()
    repos.write(repos.device, "web/index.html", "device work\n")
    assert "local changes" in repos.deploy("preview", commit, bundle, check=False)
    assert (repos.device / "web/index.html").read_text() == "device work\n"
    repos.assert_base()


def test_ignored_file_collision_is_rejected(repos):
    """Prevent a candidate from overwriting an ignored device file."""
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
    """Reject private, runtime and separately deployed paths."""
    commit, bundle = repos.candidate(path, "private or separately deployed file\n")
    assert "protected path" in repos.deploy("preview", commit, bundle, check=False)
    repos.assert_base()


def test_invalid_python_is_rejected_before_checkout(repos):
    """Leave the device at its base when candidate syntax is invalid."""
    commit, bundle = repos.candidate("apps/example.py", "def :\n")
    assert "invalid syntax" in repos.deploy("preview", commit, bundle, check=False)
    repos.assert_base()


def test_bundle_must_match_requested_commit(repos):
    """Reject transport contents that identify a different commit."""
    _, bundle = repos.candidate()
    assert "Bundle HEAD" in repos.deploy("preview", repos.base, bundle, check=False)
    repos.assert_base()


def test_review_changes_must_be_previewed_again(repos):
    """Prevent releasing reviewed contents different from the active preview."""
    candidate, bundle = repos.candidate()
    repos.deploy("preview", candidate, bundle)
    repos.command(repos.source, "switch", "main")
    reviewed, _ = repos.candidate(content="different reviewed page\n")
    repos.command(repos.source, "push", "origin", "main")
    assert "differs from the tested preview" in repos.deploy("release", reviewed, check=False)
    assert repos.command(repos.device, "rev-parse", "HEAD") == candidate
    assert (repos.device / ".git/rider-preview.json").exists()


def test_wrong_release_commit_is_rejected(repos):
    """Require the expected full revision to match origin main."""
    assert "expected merged commit" in repos.deploy("release", "0" * 40, check=False)
    repos.assert_base()


def test_wrong_base_is_rejected(repos):
    """Refuse the first preview when its base does not match device main."""
    candidate, bundle = repos.candidate()
    repos.base = "0" * 40
    assert "local base commit" in repos.deploy("preview", candidate, bundle, check=False)
    assert repos.command(repos.device, "branch", "--show-current") == "main"


def test_deployment_lock_is_not_removed_by_another_run(repos):
    """Preserve a deployment lock owned by another invocation."""
    lock = repos.device / ".git/rider-deploy.lock"
    lock.write_text("other operation")
    assert "rider-deploy.lock" in repos.deploy("rollback", check=False)
    assert lock.read_text() == "other operation"
    repos.assert_base()


def test_rollback_preserves_unexpected_checkout(repos):
    """Refuse rollback after an unexpected manual checkout change."""
    commit, bundle = repos.candidate()
    repos.deploy("preview", commit, bundle)
    repos.command(repos.device, "switch", "--detach", commit)
    assert "no longer matches" in repos.deploy("rollback", check=False)
    assert repos.command(repos.device, "rev-parse", "HEAD") == commit
    assert repos.command(repos.device, "branch", "--show-current") == ""


def test_secret_removed_from_final_tree_is_rejected_before_ssh(repos, monkeypatch):
    """Block private history locally even when its file no longer exists."""
    repos.candidate(".env.local", "do-not-transfer-this-history\n")
    repos.command(repos.source, "rm", ".env.local")
    repos.command(repos.source, "commit", "-m", "remove local configuration")
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    globals_map = module["main"].__globals__
    monkeypatch.setitem(globals_map, "ROOT", repos.source)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "preview", "--base", repos.base])

    def forbidden_ssh(*args):
        """Fail if private history reaches the transport boundary."""
        raise AssertionError("Private history must be rejected before transport")

    monkeypatch.setitem(globals_map, "ssh", forbidden_ssh)
    with pytest.raises(RuntimeError, match="protected path"):
        module["main"]()


def test_motion_scope_allows_only_its_adapter_and_tap():
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    with pytest.raises(RuntimeError):
        module["check_paths"](["drivers/xgo/adapter.py"])
    module["check_paths"](["drivers/xgo/adapter.py"], True)
    module["check_paths"](["drivers/xgo/sniffer.py"], True)
    for path in ("drivers/other.py", "systemd/motion-executor.service", "evn.ssh.local"):
        with pytest.raises(RuntimeError):
            module["check_paths"]([path], True)


def test_motion_preview_stops_before_checkout_and_restarts(repos, monkeypatch):
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    original_run = module["preview"].__globals__["run"]
    calls = []

    def run(args, *a, **kwargs):
        if "systemctl" in args:
            calls.append((tuple(args), repos.command(repos.device, "rev-parse", "HEAD")))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return original_run(args, *a, **kwargs)

    monkeypatch.setitem(module["preview"].__globals__, "run", run)
    commit, bundle = repos.candidate("drivers/xgo/adapter.py", "# fake adapter\n")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(bundle)))
    record = repos.device / ".git/rider-preview.json"
    module["preview"](
        repos.device, record, {"base": repos.base, "commit": commit, "restart_api": False, "restart_motion": True}
    )
    assert next(head for args, head in calls if "stop" in args) == repos.base
    assert next(head for args, head in calls if "start" in args) == commit
    assert json.loads(record.read_text())["restart_motion"] is True


def test_resource_scope_is_narrow_and_keeps_private_files_denied():
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    allowed = ["drivers/lcd/board.py", "drivers/led.py", "scripts/sys_control.sh", "scripts/led-backend.py"]
    with pytest.raises(RuntimeError):
        module["check_paths"](allowed)
    module["check_paths"](allowed, resource_scope=True)
    for path in [
        "drivers/xgo/adapter.py",
        "systemd/rider-api.service",
        "scripts/systemd-sync.sh",
        ".env",
        "data/state.json",
    ]:
        with pytest.raises(RuntimeError):
            module["check_paths"]([path], resource_scope=True)


def test_resource_preview_and_rollback_close_old_owners_and_preserve_motion(repos, monkeypatch):
    module = runpy.run_path(str(SCRIPT), run_name="deployment_test")
    globals_map = module["preview"].__globals__
    calls = []
    monkeypatch.setitem(globals_map, "check_api_active", lambda: calls.append("api-active"))
    monkeypatch.setitem(globals_map, "restart_api", lambda: calls.append("api-start"))
    monkeypatch.setitem(globals_map, "resource_preflight", lambda: calls.append("owners") or True)
    monkeypatch.setitem(globals_map, "pause_resources", lambda: calls.append("api-lcd-stop"))
    monkeypatch.setitem(globals_map, "resume_display", lambda active: calls.append(("lcd-start", active)))
    commit, bundle = repos.candidate("drivers/lcd/board.py", "BOARD = 0\n")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(bundle)))
    record = repos.device / ".git/rider-preview.json"
    module["preview"](
        repos.device, record, {"base": repos.base, "commit": commit, "restart_api": True, "resource_scope": True}
    )
    assert calls == ["api-active", "owners", "api-lcd-stop", "api-start", ("lcd-start", True)]
    assert json.loads(record.read_text())["resource_scope"] is True
    calls.clear()
    module["rollback"](repos.device, record)
    assert calls == ["owners", "api-lcd-stop", "api-start", ("lcd-start", True)]
    repos.assert_base()
