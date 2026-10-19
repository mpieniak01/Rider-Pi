"""Concurrent encoder and heartbeat status writes remain atomic and independent."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from apps.camera import pipeline_runtime


def test_encoder_and_heartbeat_do_not_replace_the_same_temporary_status(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path))
    synchronize = threading.Barrier(2)
    replace = pipeline_runtime.os.replace
    temporary_paths = []

    def interleaved_replace(source, target):
        if Path(target).name == "status.json":
            temporary_paths.append(str(source))
            # Both writers finish their JSON before either rename, reproducing
            # the native encoder callback vs 0.5s main-loop heartbeat race.
            synchronize.wait(timeout=2)
        return replace(source, target)

    monkeypatch.setattr(pipeline_runtime.os, "replace", interleaved_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [
            pool.submit(pipeline_runtime.write_status, {"state": "active", "sequence": sequence}) for sequence in (1, 2)
        ]
        for job in jobs:
            job.result(timeout=3)
    assert len(set(temporary_paths)) == 2
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["state"] == "active"
    assert status["sequence"] in {1, 2}
    assert status["observed_monotonic_ns"] > 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["status.json"]


def test_failed_atomic_status_replace_cleans_its_own_temporary_file(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_RUNTIME", str(tmp_path))

    def fail(*_):
        raise OSError("fixture replace failed")

    monkeypatch.setattr(pipeline_runtime.os, "replace", fail)
    with pytest.raises(OSError, match="fixture replace failed"):
        pipeline_runtime.write_status({"state": "active"})
    assert list(tmp_path.iterdir()) == []
