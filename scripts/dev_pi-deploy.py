#!/usr/bin/env python3
"""Preview a local commit on the Pi over SSH, then release merged main."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd()


def run(args, cwd=None, check=True):
    """Run a bounded command and report its captured failure output."""
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Command failed")
    return result


def git(repo, *args):
    """Run Git in the selected checkout and return trimmed output."""
    return run(["git", *args], cwd=repo).stdout.strip()


def check_clean(repo):
    """Refuse deployment when tracked or ordinary untracked work exists."""
    if git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Checkout has local changes; preserve them before deployment.")


def changed_paths(repo, base, target):
    """List every changed path, treating renames as deletion and addition."""
    output = run(["git", "diff", "--name-only", "--no-renames", "-z", base, target], cwd=repo).stdout
    return [p for p in output.split("\0") if p]


def check_paths(paths, restart_motion=False):
    """Reject private data and changes requiring a separate deployment scope."""
    for path in paths:
        parts = PurePosixPath(path).parts
        name = parts[-1]
        private = (
            "_to_do" in parts
            or "_done" in parts
            or path.startswith("config/local/")
            or path == "config/local"
            or path.startswith(("logs/", "data/", "snapshots/", ".pids/", "models/"))
            or name == "evn.ssh.local"
            or (name.startswith(".env") and not name.endswith(".example"))
        )
        critical = path.startswith(("systemd/", "drivers/", "scripts/sys_", "requirements"))
        critical = critical or path in {"scripts/systemd-sync.sh", "pyproject.toml"}
        if path == "drivers/xgo/adapter.py" and restart_motion:
            critical = False  # Explicit motion deployment scope, never a general driver bypass.
        if private or critical:
            raise RuntimeError(f"Separate deployment scope required for protected path: {path}")


def check_local_files(repo, paths):
    """Prevent new tracked paths from replacing existing local files."""
    if not paths:
        return
    tracked = set(run(["git", "ls-files", "-z"], cwd=repo).stdout.split("\0"))
    for path in paths:
        file_path = repo / path
        if path not in tracked and (file_path.exists() or file_path.is_symlink()):
            raise RuntimeError(f"Deployment would overwrite a local file: {path}")


def check_python(repo, target, paths):
    """Parse changed Python blobs with the current device interpreter."""
    for path in paths:
        if not path.endswith(".py"):
            continue
        exists = run(["git", "cat-file", "-e", f"{target}:{path}"], cwd=repo, check=False)
        if not exists.returncode:
            source = run(["git", "show", f"{target}:{path}"], cwd=repo).stdout
            ast.parse(source, filename=path)


def check_history(repo, base, target, restart_motion=False):
    """Validate every bundled commit, including files later removed."""
    for commit in git(repo, "rev-list", f"{base}..{target}").splitlines():
        paths = run(
            ["git", "diff-tree", "-m", "--no-commit-id", "--name-only", "-r", "-z", commit], cwd=repo
        ).stdout.split("\0")
        check_paths([path for path in paths if path], restart_motion)


def read_record(path):
    """Read an optional deployment record from the Git directory."""
    return json.loads(path.read_text()) if path.exists() else None


def write_record(path, data):
    """Replace a deployment record atomically with owner-only permissions."""
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream)
    os.replace(temporary, path)


def restart_api():
    """Restart only the API service and wait for its HTTP health endpoint."""
    run(["sudo", "-n", "systemctl", "restart", "rider-api.service"])
    for _ in range(20):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    raise RuntimeError("API health check failed after restart; restore the recorded previous revision.")


def check_api_active():
    """Require an already active API before a deployment restarts it."""
    result = run(["systemctl", "is-active", "rider-api.service"], check=False)
    if result.returncode:
        raise RuntimeError("API is not active; restarting an inactive service requires its own scope.")


def status(repo, record_path):
    """Describe the checked-out revision and any recorded preview."""
    return {
        "branch": git(repo, "branch", "--show-current"),
        "commit": git(repo, "rev-parse", "HEAD"),
        "dirty": bool(git(repo, "status", "--porcelain", "--untracked-files=normal")),
        "preview": read_record(record_path),
    }


def preview(repo, record_path, request):
    """Check a Git bundle and activate a reversible preview commit."""
    check_clean(repo)
    previous = read_record(record_path)
    restart_required = request["restart_api"] or bool(previous and previous["restart_api"])
    restart_on_rollback = restart_required or bool(previous and previous["restart_api"])
    if restart_required:
        check_api_active()
    base, target = request["base"], request["commit"]
    current, branch = git(repo, "rev-parse", "HEAD"), git(repo, "branch", "--show-current")
    if previous:
        if previous["base"] != base or current != previous["commit"] or branch != previous["preview_branch"]:
            raise RuntimeError("Active preview does not match its record; inspect status first.")
    elif current != base or branch != "main":
        raise RuntimeError("First preview requires clean main at the local base commit.")

    transfer_base = request.get("transfer_base", current)
    if current != transfer_base:
        raise RuntimeError("Device revision changed since preflight; run preview again.")
    if current == target and "transfer_base" in request:
        if request.get("restart_motion"):
            if previous:
                write_record(record_path, dict(previous, restart_motion=True))
            run(["sudo", "-n", "systemctl", "restart", "motion-executor.service"])
            run(["systemctl", "is-active", "motion-executor.service"])
        if restart_required:
            if previous:
                write_record(record_path, dict(previous, restart_api=True))
            restart_api()
        return {"action": "preview", "files": [], "unchanged": True, **status(repo, record_path)}

    with tempfile.NamedTemporaryFile(dir=record_path.parent, suffix=".bundle") as bundle:
        shutil.copyfileobj(sys.stdin.buffer, bundle)
        bundle.flush()
        git(repo, "bundle", "verify", bundle.name)
        git(repo, "fetch", bundle.name, "HEAD")
    if git(repo, "rev-parse", "FETCH_HEAD") != target:
        raise RuntimeError("Bundle HEAD does not match the requested commit.")
    git(repo, "merge-base", "--is-ancestor", base, target)
    git(repo, "merge-base", "--is-ancestor", transfer_base, target)
    check_history(repo, transfer_base, target, request.get("restart_motion", False))
    paths = changed_paths(repo, transfer_base, target)
    check_paths(paths, request.get("restart_motion", False))
    check_local_files(repo, paths)
    check_python(repo, target, paths)
    preview_branch = f"rider-preview/{target[:12]}"
    existing = run(["git", "rev-parse", "--verify", f"refs/heads/{preview_branch}"], cwd=repo, check=False)
    if not existing.returncode and existing.stdout.strip() != target:
        raise RuntimeError("Preview branch already exists at a different commit; preserve it first.")
    record = {
        "base": base,
        "branch": "main",
        "commit": target,
        "preview_branch": preview_branch,
        "restart_api": restart_on_rollback,
        "restart_motion": request.get("restart_motion", False) or bool(previous and previous.get("restart_motion")),
    }
    if request.get("restart_motion"):
        run(["systemctl", "is-active", "motion-executor.service"])
        run(["sudo", "-n", "systemctl", "stop", "motion-executor.service"])
    try:
        write_record(record_path, record)
        if existing.returncode:
            git(repo, "switch", "-c", preview_branch, target)
        else:
            git(repo, "switch", preview_branch)
    except RuntimeError:
        if previous:
            write_record(record_path, previous)
        elif record_path.exists():
            record_path.unlink()
        if request.get("restart_motion") and git(repo, "rev-parse", "HEAD") == current:
            run(["sudo", "-n", "systemctl", "start", "motion-executor.service"])
        raise
    if request.get("restart_motion"):
        run(["sudo", "-n", "systemctl", "start", "motion-executor.service"])
        run(["systemctl", "is-active", "motion-executor.service"])
    if restart_required:
        restart_api()
    return {"action": "preview", "files": paths, **status(repo, record_path)}


def rollback(repo, record_path):
    """Restore saved main and the API when its restart was recorded."""
    check_clean(repo)
    record = read_record(record_path)
    if not record:
        raise RuntimeError("There is no active preview to roll back.")
    current, branch = git(repo, "rev-parse", "HEAD"), git(repo, "branch", "--show-current")
    if git(repo, "rev-parse", record["branch"]) != record["base"]:
        raise RuntimeError("Saved main changed; preserve it before rollback.")
    if record.get("restart_motion") and current == record["commit"] and branch == record["preview_branch"]:
        run(["sudo", "-n", "systemctl", "stop", "motion-executor.service"])
    if current == record["commit"] and branch == record["preview_branch"]:
        git(repo, "switch", record["branch"])
    elif current != record["base"] or branch != record["branch"]:
        raise RuntimeError("Device checkout no longer matches the preview record.")
    if record.get("restart_motion"):
        run(["sudo", "-n", "systemctl", "start", "motion-executor.service"])
        run(["systemctl", "is-active", "motion-executor.service"])
    if record["restart_api"]:
        restart_api()
    record_path.unlink()
    return {"action": "rollback", **status(repo, record_path)}


def release(repo, record_path, request):
    """Fast-forward to expected GitHub main after checking preview contents."""
    check_clean(repo)
    previous = read_record(record_path)
    current, branch = git(repo, "rev-parse", "HEAD"), git(repo, "branch", "--show-current")
    if previous:
        if current != previous["commit"] or branch != previous["preview_branch"]:
            raise RuntimeError("Device checkout no longer matches the preview record.")
        if git(repo, "rev-parse", "main") != previous["base"]:
            raise RuntimeError("Saved main changed; inspect it before release.")
    elif branch != "main":
        raise RuntimeError("Release requires clean main or a recorded preview.")
    if request["restart_api"]:
        check_api_active()
    git(repo, "fetch", "origin", "main")
    target = git(repo, "rev-parse", "origin/main")
    if target != request["commit"]:
        raise RuntimeError("GitHub main differs from the expected merged commit.")
    base = previous["base"] if previous else current
    git(repo, "merge-base", "--is-ancestor", base, target)
    paths = changed_paths(repo, base, target)
    check_paths(paths, request.get("restart_motion", False))
    check_local_files(repo, paths)
    check_python(repo, target, paths)
    if previous and git(repo, "rev-parse", f"{current}^{{tree}}") != git(repo, "rev-parse", f"{target}^{{tree}}"):
        raise RuntimeError("Reviewed main differs from the tested preview; preview the new content first.")
    release_record = record_path.with_name("rider-last-release.json")
    last_release = read_record(release_record)
    if base != target or not last_release or last_release["commit"] != target:
        write_record(release_record, {"previous": base, "commit": target})
    if request.get("restart_motion"):
        run(["systemctl", "is-active", "motion-executor.service"])
        run(["sudo", "-n", "systemctl", "stop", "motion-executor.service"])
    if previous:
        git(repo, "switch", "main")
    git(repo, "merge", "--ff-only", "origin/main")
    if previous:
        record_path.unlink()
    if request.get("restart_motion"):
        run(["sudo", "-n", "systemctl", "start", "motion-executor.service"])
        run(["systemctl", "is-active", "motion-executor.service"])
    if request["restart_api"]:
        restart_api()
    return {"action": "release", "previous": base, "files": paths, **status(repo, record_path)}


def remote(request):
    """Dispatch a device operation under an exclusive deployment lock."""
    repo = Path(request["repo"]).resolve()
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise RuntimeError("Device path must be the Git checkout root.")
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
    record_path = git_dir / "rider-preview.json"
    if request["action"] == "status":
        return status(repo, record_path)
    lock = git_dir / "rider-deploy.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        if request["action"] == "preview":
            return preview(repo, record_path, request)
        if request["action"] == "rollback":
            return rollback(repo, record_path)
        return release(repo, record_path, request)
    finally:
        lock.unlink()


def ssh(env_file, request, bundle):
    """Send source, request and bundle using the locally configured SSH password."""
    if not env_file.is_file() or env_file.stat().st_mode & 0o077:
        raise RuntimeError("SSH env file must exist with mode 600.")
    destination = run(
        [
            "bash",
            "-c",
            'source "$1"; printf "%s\\n%s\\n%s\\n" "$SSH_HOST" "$SSH_USER" "$SSH_PORT"',
            "rider-deploy",
            str(env_file),
        ]
    ).stdout.splitlines()
    if len(destination) != 3 or not all(destination[:2]):
        raise RuntimeError("SSH_HOST and SSH_USER are required in the local env file.")
    host, user, port = destination
    port = port or "22"
    if host.startswith("-") or user.startswith("-") or not port.isdigit():
        raise RuntimeError("Invalid SSH destination.")
    source = Path(__file__).read_text()
    command = shlex.join(["python3", "-c", source, "_remote", json.dumps(request)])
    with tempfile.TemporaryDirectory(prefix="rider-ssh-") as directory:
        askpass = Path(directory) / "askpass"
        askpass.write_text("#!/bin/bash\nsource " + shlex.quote(str(env_file)) + '\nprintf "%s\\n" "$SSH_PASSWORD"\n')
        askpass.chmod(0o700)
        environment = dict(os.environ, SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE="force", DISPLAY=":0")
        args = [
            "ssh",
            "-T",
            "-p",
            port,
            "-o",
            "ConnectTimeout=8",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
            f"{user}@{host}",
            command,
        ]
        result = subprocess.run(args, input=bundle, capture_output=True, env=environment, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.decode().strip() or "Device deployment failed.")
        return json.loads(result.stdout)


def main():
    """Build a local deployment request or handle the transmitted device request."""
    if len(sys.argv) > 1 and sys.argv[1] == "_remote":
        print(json.dumps(remote(json.loads(sys.argv[2]))))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("preview", "status", "rollback", "release"):
        command = commands.add_parser(action)
        command.add_argument("--env-file", type=Path, default=ROOT / "evn.ssh.local")
        command.add_argument("--device-repo", default="/home/pi/robot")
        command.add_argument("--restart-api", action="store_true")
        command.add_argument(
            "--restart-motion",
            action="store_true",
            help="Explicit motion scope: stop executor before checkout, restart disarmed; allows its XGO adapter",
        )
        if action == "preview":
            command.add_argument("--base", default="origin/main")
        if action == "release":
            command.add_argument("--commit", required=True, help="Full SHA of merged main")
    args = parser.parse_args()
    started = time.monotonic()
    request = {
        "action": args.action,
        "repo": args.device_repo,
        "restart_api": args.restart_api,
        "restart_motion": args.restart_motion,
    }
    bundle_bytes = b""
    if args.action == "preview":
        check_clean(ROOT)
        request["base"] = git(ROOT, "rev-parse", f"{args.base}^{{commit}}")
        request["commit"] = git(ROOT, "rev-parse", "HEAD")
        if request["commit"] == request["base"]:
            raise RuntimeError("Commit your local change on a feature branch before previewing it.")
        git(ROOT, "merge-base", "--is-ancestor", request["base"], request["commit"])
        # Check all history for private files before SSH. The exact motion adapter
        # may already be in the recorded preview; its deployment scope is checked
        # again against the actual transfer base below and on the device.
        check_history(ROOT, request["base"], request["commit"], True)
        device = ssh(args.env_file.resolve(), {"action": "status", "repo": args.device_repo}, b"")
        if device["dirty"]:
            raise RuntimeError("Device checkout has local changes; preserve them before preview.")
        previous = device["preview"]
        if previous:
            if (
                previous["base"] != request["base"]
                or device["commit"] != previous["commit"]
                or device["branch"] != previous["preview_branch"]
            ):
                raise RuntimeError("Active preview differs from the local base or recorded device state.")
        elif device["commit"] != request["base"] or device["branch"] != "main":
            raise RuntimeError("First preview requires clean device main at the local base commit.")
        request["transfer_base"] = device["commit"]
        git(ROOT, "merge-base", "--is-ancestor", request["transfer_base"], request["commit"])
        check_history(ROOT, request["transfer_base"], request["commit"], args.restart_motion)
        check_paths(changed_paths(ROOT, request["transfer_base"], request["commit"]), args.restart_motion)
        if request["transfer_base"] != request["commit"]:
            with tempfile.TemporaryDirectory(prefix="rider-bundle-") as directory:
                bundle_path = Path(directory) / "preview.bundle"
                git(ROOT, "bundle", "create", str(bundle_path), f"{request['transfer_base']}..HEAD")
                bundle_bytes = bundle_path.read_bytes()
    elif args.action == "release":
        if len(args.commit) != 40 or any(c not in "0123456789abcdef" for c in args.commit):
            raise RuntimeError("Release requires a full 40-character merged commit SHA.")
        request["commit"] = args.commit
    result = ssh(args.env_file.resolve(), request, bundle_bytes)
    result["elapsed_s"] = round(time.monotonic() - started, 2)
    result["transfer_bytes"] = len(bundle_bytes)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, SyntaxError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
