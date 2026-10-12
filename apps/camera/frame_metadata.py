"""Source frame timing bound to an atomic image's file identity, without hashing.

captured_at is the camera owner's successful read completion (Unix seconds).
It is not a sensor exposure timestamp. Encoding/distribution do not refresh it.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_METADATA_BYTES = 2048


def file_identity(stat) -> dict:
    return {name: getattr(stat, 'st_' + name) for name in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}


def metadata_path(path: Path) -> Path:
    target = path.resolve()
    return target.with_name(target.name + '.metadata.json')


def _valid_time(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def write_metadata(path: Path, *, captured_at, frame_id: str, shape=None) -> bool:
    """Image write succeeds independently; failed sidecars yield explicit mtime."""
    if not _valid_time(captured_at) or not isinstance(frame_id, str) or not 0 < len(frame_id) <= 64:
        return False
    target = metadata_path(path)
    temp = target.with_name(target.name + '.tmp')
    try:
        metadata = {
            'version': 1,
            'captured_at': captured_at,
            'timestamp_source': 'capture',
            'frame_id': frame_id,
            'file': file_identity(path.stat()),
        }
        if shape is not None:
            metadata['shape'] = {'width': int(shape[1]), 'height': int(shape[0])}
        encoded = json.dumps(metadata, allow_nan=False, separators=(',', ':')).encode()
        if len(encoded) > MAX_METADATA_BYTES:
            return False
        temp.write_bytes(encoded)
        os.replace(temp, target)
        return True
    except (OSError, ValueError, TypeError, IndexError):
        return False
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def read_frame(path: Path) -> tuple[bytes, dict] | None:
    """Stable fd read; a sidecar for another inode/revision cannot certify age."""
    try:
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            if not 0 < before.st_size <= MAX_FRAME_BYTES:
                return None
            data = stream.read(MAX_FRAME_BYTES + 1)
            after = os.fstat(stream.fileno())
        identity = file_identity(after)
        if file_identity(before) != identity or len(data) != after.st_size or len(data) > MAX_FRAME_BYTES:
            return None
    except OSError:
        return None
    observed = {
        'mtime': after.st_mtime,
        'observed_at': after.st_mtime,
        'timestamp_source': 'file_mtime',
        'file_identity': identity,
    }
    try:
        with metadata_path(path).open('rb') as stream:
            encoded = stream.read(MAX_METADATA_BYTES + 1)
        if len(encoded) > MAX_METADATA_BYTES:
            return data, observed
        metadata = json.loads(encoded)
        if (
            not isinstance(metadata, dict)
            or type(metadata.get('version')) is not int
            or metadata['version'] != 1
            or not isinstance(metadata.get('file'), dict)
            or metadata['file'] != identity
            or not _valid_time(metadata.get('captured_at'))
            or metadata.get('timestamp_source') != 'capture'
            or not isinstance(metadata.get('frame_id'), str)
            or not 0 < len(metadata['frame_id']) <= 64
        ):
            return data, observed
        observed.update(
            captured_at=metadata['captured_at'],
            observed_at=metadata['captured_at'],
            timestamp_source='capture',
            frame_id=metadata['frame_id'],
        )
        shape = metadata.get('shape')
        if isinstance(shape, dict) and all(
            type(shape.get(axis)) is int and 0 < shape[axis] <= 16384 for axis in ('width', 'height')
        ):
            observed['shape'] = shape
    except (OSError, ValueError, TypeError):
        pass
    return data, observed
