"""Speaker ownership and microphone suppression use the same Linux lock file."""

from __future__ import annotations

import fcntl
import json
import math
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from common.runtime_lock import exclusive

# The capture process is closed during playback and this acoustic drain period.
PLAYBACK_DRAIN_S = 0.35
_MAX_RECORD = 1024


def lock_path() -> Path:
    state = Path(os.getenv('FEATURE_STATE_PATH', '/run/rider-motion/feature_state.json'))
    return Path(os.getenv('RIDER_AUDIO_LOCK_PATH', str(state.parent / 'audio-playback.lock')))


def _boot_id() -> str:
    # Linux boot identity scopes monotonic timestamps across processes/restarts.
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def _write_record(fd: int, record: dict) -> None:
    data = json.dumps(record, separators=(',', ':'), allow_nan=False).encode('ascii')
    if os.pwrite(fd, data, 0) != len(data):
        raise OSError('incomplete playback ownership record')
    os.ftruncate(fd, len(data))


@contextmanager
def own_playback():
    """Hold the existing speaker lock from before player start to after close.

    The generation changes even for playback shorter than a microphone frame.
    No independent active flag is used: only flock ownership denotes activity.
    """
    with exclusive(lock_path(), timeout_s=0) as fd:
        record = {'v': 1, 'boot_id': _boot_id(), 'generation': uuid.uuid4().hex, 'ended_at': None}
        _write_record(fd, record)
        try:
            yield
        finally:
            record['ended_at'] = time.monotonic()
            _write_record(fd, record)


@dataclass(frozen=True)
class PlaybackState:
    active: bool = False
    generation: str | None = None
    quiet_until: float = 0.0


class PlaybackObserver:
    """Read bounded ownership metadata without keeping the speaker locked."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self.path = lock_path()
        self.clock = clock
        self.boot_id = _boot_id()
        self.fd = None
        self._guard = threading.Lock()
        self.closed = False
        self.orphan_generation = None
        self.orphan_quiet_until = 0.0

    def snapshot(self) -> PlaybackState:
        # OFF may close this observer from the service's signal thread.
        with self._guard:
            return self._snapshot()

    def _snapshot(self) -> PlaybackState:
        if self.closed:
            raise OSError('playback observer closed')
        try:
            identity = self.path.stat()
        except FileNotFoundError:
            self._close_fd()
            return PlaybackState()
        if self.fd is not None:
            current = os.fstat(self.fd)
            if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
                self._close_fd()
        if self.fd is None:
            self.fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return PlaybackState(active=True)
        try:
            data = os.pread(self.fd, _MAX_RECORD + 1, 0)
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        return self._state_from_record(data)

    def _state_from_record(self, data):
        if not data:
            return PlaybackState()  # Existing empty lock, before first playback.
        if len(data) > _MAX_RECORD:
            raise ValueError('oversized playback ownership record')
        record = json.loads(data)
        if not isinstance(record, dict) or record.get('v') != 1:
            raise ValueError('invalid playback ownership record')
        if record.get('boot_id') != self.boot_id:
            return PlaybackState()
        generation = record.get('generation')
        if not isinstance(generation, str) or len(generation) != 32:
            raise ValueError('invalid playback generation')
        ended_at = record.get('ended_at')
        if ended_at is None:
            # Owner died before writing completion. Once per generation, drain
            # after observing the released lock; do not restore an old buffer.
            if generation != self.orphan_generation:
                self.orphan_generation = generation
                self.orphan_quiet_until = self.clock() + PLAYBACK_DRAIN_S
            quiet_until = self.orphan_quiet_until
        elif (
            isinstance(ended_at, bool)
            or not isinstance(ended_at, (int, float))
            or not math.isfinite(ended_at)
            or ended_at < 0
        ):
            raise ValueError('invalid playback completion time')
        else:
            quiet_until = ended_at + PLAYBACK_DRAIN_S
        return PlaybackState(generation=generation, quiet_until=quiet_until)

    def _close_fd(self) -> None:
        fd, self.fd = self.fd, None
        if fd is not None:
            os.close(fd)

    def close(self) -> None:
        with self._guard:
            self.closed = True
            self._close_fd()
