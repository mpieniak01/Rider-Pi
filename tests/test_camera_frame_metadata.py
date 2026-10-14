"""File capture timing and distributor use temporary images, not camera devices."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.camera import frame_distributor, frame_metadata


def image(tmp_path, data=b'\xff\xd8\xffjpeg'):
    path = tmp_path / 'raw.jpg'
    path.write_bytes(data)
    return path


def test_source_capture_time_belongs_to_matching_atomic_file(tmp_path):
    path = image(tmp_path)
    assert frame_metadata.write_metadata(path, captured_at=990, frame_id='capture-12', shape=(240, 320))
    data, metadata = frame_metadata.read_frame(path)
    assert data == path.read_bytes()
    assert metadata['captured_at'] == metadata['observed_at'] == 990
    assert metadata['timestamp_source'] == 'capture'
    assert metadata['frame_id'] == 'capture-12'
    assert metadata['shape'] == {'width': 320, 'height': 240}


def test_replaced_file_cannot_inherit_old_capture_time_even_same_size_mtime(tmp_path):
    path = image(tmp_path)
    original = path.stat()
    assert frame_metadata.write_metadata(path, captured_at=990, frame_id='old')
    replacement = tmp_path / 'next.jpg'
    replacement.write_bytes(path.read_bytes())
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    os.replace(replacement, path)
    _, metadata = frame_metadata.read_frame(path)
    assert metadata['timestamp_source'] == 'file_mtime'
    assert 'captured_at' not in metadata
    assert metadata['observed_at'] == path.stat().st_mtime


def test_alias_reads_target_sidecar(tmp_path):
    path = image(tmp_path)
    assert frame_metadata.write_metadata(path, captured_at=990, frame_id='capture-12')
    alias = tmp_path / 'alias.jpg'
    alias.symlink_to(path.name)
    assert frame_metadata.read_frame(alias)[1]['captured_at'] == 990


@pytest.mark.parametrize('sidecar', [None, b'not-json', b'[]', b'{}', b'x' * 2049])
def test_missing_or_bad_sidecar_is_explicit_file_mtime(tmp_path, sidecar):
    path = image(tmp_path)
    if sidecar is not None:
        frame_metadata.metadata_path(path).write_bytes(sidecar)
    data, metadata = frame_metadata.read_frame(path)
    assert data == path.read_bytes()
    assert metadata['timestamp_source'] == 'file_mtime'
    assert 'captured_at' not in metadata


@pytest.mark.parametrize('captured', [None, 0, -1, True, float('inf'), float('nan')])
def test_unknown_capture_time_never_becomes_write_time(tmp_path, captured):
    path = image(tmp_path)
    assert not frame_metadata.write_metadata(path, captured_at=captured, frame_id='capture-1')
    assert frame_metadata.read_frame(path)[1]['timestamp_source'] == 'file_mtime'


def test_oversized_file_not_loaded_or_hashed(tmp_path):
    path = image(tmp_path)
    with path.open('wb') as stream:
        stream.truncate(2 * 1024 * 1024 + 1)
    assert frame_metadata.read_frame(path) is None


def test_changed_file_during_read_is_dropped(tmp_path, monkeypatch):
    path = image(tmp_path)
    stat = path.stat()
    before = SimpleNamespace(
        **{
            name: getattr(stat, name)
            for name in (
                'st_dev',
                'st_ino',
                'st_size',
                'st_mtime_ns',
                'st_ctime_ns',
                'st_mtime',
            )
        }
    )
    after = SimpleNamespace(**vars(before))
    after.st_mtime_ns += 1
    statuses = iter((before, after))
    monkeypatch.setattr(frame_metadata.os, 'fstat', lambda _: next(statuses))
    assert frame_metadata.read_frame(path) is None


def test_distributor_preserves_capture_and_shape_without_decoding(tmp_path):
    path = image(tmp_path)
    assert frame_metadata.write_metadata(path, captured_at=990, frame_id='source-1', shape=(240, 320))
    distributor = object.__new__(frame_distributor.FrameDistributor)
    distributor.frame_mode, distributor.frame_id = 'raw', 5
    data, metadata = distributor._load_frame_bytes(str(path))
    assert data == path.read_bytes()
    assert metadata['id'] == 5 and metadata['frame_id'] == 'source-1'
    assert metadata['captured_at'] == 990 and metadata['timestamp_source'] == 'capture'
    assert metadata['shape'] == {'width': 320, 'height': 240}
    assert 'cv2' not in frame_distributor.__dict__ and 'np' not in frame_distributor.__dict__


def test_preview_keeps_read_completion_time_before_encoding(monkeypatch):
    import numpy as np

    from apps.camera import preview_lcd

    now = [1000.0]
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    captured, closed = [], []

    class Reader:
        count = 0

        def __call__(self):
            self.count += 1
            if self.count > 1:
                raise KeyboardInterrupt()
            return True, frame

        def close(self):
            closed.append(True)

    def save(_, **kwargs):
        captured.append(kwargs)
        now[0] += 5

    monkeypatch.setattr(preview_lcd, 'open_camera', lambda *_: (Reader(), 'fixture'))
    monkeypatch.setattr(preview_lcd, '_lcd_init', lambda: None)
    monkeypatch.setattr(preview_lcd, 'DETECTOR', 'none')
    monkeypatch.setattr(preview_lcd, 'LCD_ok', False)
    monkeypatch.setattr(preview_lcd, 'ENV_NO_DRAW', True)
    monkeypatch.setattr(preview_lcd, 'time', SimpleNamespace(time=lambda: now[0], sleep=lambda _: None))
    monkeypatch.setattr(preview_lcd, 'save_last_frame', save)
    monkeypatch.setattr(preview_lcd, 'save_raw_snapshot', save)
    monkeypatch.setattr(preview_lcd, 'hb_publish', lambda **_: None)
    assert preview_lcd.main() == 0
    assert captured[0] == captured[1]
    assert captured[0]['captured_at'] == 1000
    assert captured[0]['frame_id'].endswith('-0')
    assert closed == [True]


def test_raw_feed_is_faster_than_ui_snapshots_and_keeps_capture_identity(monkeypatch):
    import numpy as np

    from apps.camera import preview_lcd

    now = [1000.0]
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    raw, last, closed = [], [], []

    class Reader:
        count = 0

        def __call__(self):
            if self.count >= 18:
                raise KeyboardInterrupt()
            self.count += 1
            now[0] += 1 / 15
            return True, frame

        def close(self):
            closed.append(True)

    monkeypatch.setattr(preview_lcd, "open_camera", lambda *_: (Reader(), "fixture"))
    monkeypatch.setattr(preview_lcd, "_lcd_init", lambda: None)
    monkeypatch.setattr(preview_lcd, "DETECTOR", "none")
    monkeypatch.setattr(preview_lcd, "LCD_ok", False)
    monkeypatch.setattr(preview_lcd, "ENV_NO_DRAW", True)
    monkeypatch.setattr(preview_lcd, "SAVE_LAST_EVERY", 10)
    monkeypatch.setattr(preview_lcd, "SAVE_RAW_EVERY", 2)
    monkeypatch.setattr(preview_lcd, "time", SimpleNamespace(time=lambda: now[0], sleep=lambda _: None))
    monkeypatch.setattr(preview_lcd, "save_last_frame", lambda _, **kw: last.append(kw))
    monkeypatch.setattr(preview_lcd, "save_raw_snapshot", lambda _, **kw: raw.append(kw))
    monkeypatch.setattr(preview_lcd, "hb_publish", lambda **_: None)
    assert preview_lcd.main() == 0
    assert len(raw) == 9 and len(last) == 2
    assert raw[0] == last[0] and raw[5] == last[1]
    assert max(b["captured_at"] - a["captured_at"] for a, b in zip(raw, raw[1:])) < 0.15
    assert len({row["frame_id"] for row in raw}) == 9
    assert closed == [True]


@pytest.mark.parametrize("raw_path", [None, "", "/fixture/raw.jpg"])
def test_raw_topic_uses_actual_raw_export_and_legacy_heartbeat_falls_back(monkeypatch, raw_path):
    messages = iter(
        [
            (
                frame_distributor.HEARTBEAT_TOPIC,
                {"mode": "preview", "last_frame_path": "/fixture/last.jpg", "raw_frame_path": raw_path},
            ),
            (None, None),
        ]
    )
    dist = object.__new__(frame_distributor.FrameDistributor)
    dist.sub = SimpleNamespace(recv=lambda **_: next(messages))
    dist.frame_path = "old"
    dist.frame_mode = "old"
    monkeypatch.setattr(frame_distributor, "FRAME_STREAM_TOPIC", b"camera.frame.raw")
    dist._drain_heartbeat()
    assert dist.frame_path == (raw_path or "/fixture/last.jpg")
    assert dist.frame_mode == ("raw" if raw_path else "preview")


def test_capture_heartbeat_exposes_both_paths_without_relabeling_preview(monkeypatch):
    from apps.camera import preview_lcd

    rows = []
    monkeypatch.setattr(preview_lcd, "_last_frame_used_path", "/fixture/last.jpg")
    monkeypatch.setattr(preview_lcd, "_raw_frame_used_path", "/fixture/raw.jpg")
    monkeypatch.setattr(preview_lcd, "publish", lambda topic, payload, **kw: rows.append(payload))
    preview_lcd.hb_publish(fps=15, lcd_active=False)
    assert rows[0]["last_frame_path"] == "/fixture/last.jpg"
    assert rows[0]["raw_frame_path"] == "/fixture/raw.jpg"
    assert rows[0]["mode"] == "preview"


def test_real_raw_save_is_advertised_with_its_matching_capture_metadata(monkeypatch, tmp_path):
    import numpy as np

    from apps.camera import preview_lcd

    rows = []
    monkeypatch.setattr(preview_lcd, "SNAP_DIR", str(tmp_path))
    monkeypatch.setattr(preview_lcd, "_SELECTED_EXT", ".jpg")
    monkeypatch.setattr(preview_lcd, "ROT", 0)
    monkeypatch.setattr(preview_lcd, "_raw_frame_used_path", None)
    monkeypatch.setattr(preview_lcd, "_last_frame_used_path", "/fixture/last.jpg")
    monkeypatch.setattr(preview_lcd, "publish", lambda topic, payload, **kw: rows.append(payload))
    preview_lcd.save_raw_snapshot(np.zeros((64, 64, 3), dtype=np.uint8), captured_at=1000, frame_id="capture-new")
    preview_lcd.hb_publish(fps=15, lcd_active=False)
    assert rows[0]["raw_frame_path"] == str(tmp_path / "raw.jpg")
    assert frame_metadata.read_frame(tmp_path / "raw.jpg")[1]["frame_id"] == "capture-new"
    assert rows[0]["last_frame_path"] == "/fixture/last.jpg"
