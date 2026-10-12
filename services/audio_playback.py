"""One bounded playback operation, reusing the shared player and ownership lock."""

from __future__ import annotations

import math
import re
import threading
import time
from collections import OrderedDict

from apps.compute.client import ComputeError, validate_wav

ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('playback_id_invalid')
    return value


class PlaybackManager:
    """No queue. Cancelled ids are tombstones so a late upload cannot start."""

    def __init__(self, *, player=None, config=None, clock=time.monotonic, wall_clock=time.time):
        self.player = player
        self.config = config
        self.clock, self.wall_clock = clock, wall_clock
        self.lock = threading.Lock()
        self.active = None
        self.recent = OrderedDict()
        self.closed = False
        self.done = threading.Event()
        self.done.set()

    def _remember(self, playback_id, result):
        self.recent[playback_id] = (self.clock() + 60, result)
        self.recent.move_to_end(playback_id)
        for key in list(self.recent):
            if self.recent[key][0] <= self.clock():
                del self.recent[key]
        while len(self.recent) > 64:
            self.recent.popitem(last=False)

    def _result(self, playback_id, state, **data):
        return {
            'ok': state == 'played',
            'playback_id': playback_id,
            'state': state,
            'observed_at': self.wall_clock(),
            'physical_completion': 'unverified',
            **data,
        }

    def execute(self, data: bytes, playback_id: str, deadline: float):
        identifier(playback_id)
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('playback_deadline_invalid')
        if not isinstance(data, bytes) or not 0 < len(data) <= 2 * 1024 * 1024:
            raise ComputeError('playback_input_size', 413)
        rate = validate_wav(data)
        event = threading.Event()
        with self.lock:
            cached = self.recent.get(playback_id)
            if cached is not None and cached[0] > self.clock():
                result = {**cached[1], 'idempotent': True}
                return result, 200 if result['state'] == 'played' else 409
            if self.closed or self.clock() >= deadline:
                result = self._result(playback_id, 'expired', error='playback_expired')
                self._remember(playback_id, result)
                return result, 409
            if self.active is not None:
                return self._result(playback_id, 'rejected', error='playback_busy'), 429
            self.active = (playback_id, event)
            self.done.clear()

        timer_done = threading.Event()

        def expire():
            if not timer_done.wait(max(0, deadline - self.clock())):
                event.set()

        timer = threading.Thread(target=expire, name='playback-deadline', daemon=True)
        result = self._result(playback_id, 'failed', error='playback_unavailable')
        try:
            timer.start()
            if event.is_set() or self.clock() >= deadline:
                result = self._result(playback_id, 'expired', error='playback_expired')
            else:
                from apps.voice.audio.playback import PlaybackConfig, play_bytes

                cfg = self.config
                if cfg is None:
                    from apps.voice.config import load

                    cfg = PlaybackConfig(**dict(load().get('playback') or {}))
                player = self.player or play_bytes
                played = False
                if not event.is_set() and self.clock() < deadline:
                    played = player(data, 'wav', cfg, sample_rate=rate, channels=1, stop_event=event)
                if event.is_set():
                    state = 'expired' if self.clock() >= deadline else 'cancelled'
                    result = self._result(playback_id, state, error='playback_' + state)
                else:
                    result = self._result(
                        playback_id,
                        'played' if played else 'failed',
                        error=None if played else 'playback_unavailable',
                        sample_rate=rate,
                        released=True,
                    )
            return result, 200 if result['ok'] else 503 if result['state'] == 'failed' else 409
        except Exception:
            result = self._result(playback_id, 'failed', error='playback_unavailable')
            return result, 503
        finally:
            timer_done.set()
            if timer.is_alive():
                timer.join(timeout=0.2)
            with self.lock:
                self.active = None
                self._remember(playback_id, result)
                self.done.set()

    def cancel(self, playback_id: str):
        identifier(playback_id)
        with self.lock:
            matching = self.active is not None and self.active[0] == playback_id
            if matching:
                self.active[1].set()
            result = self._result(playback_id, 'cancelled', error='playback_cancelled')
            self._remember(playback_id, result)
        if matching:
            self.done.wait(1.0)
        with self.lock:
            released = self.active is None or self.active[0] != playback_id
            return {
                'ok': True,
                'playback_id': playback_id,
                'state': 'cancelled' if released else 'cancelling',
                'released': released,
                'pending': not released,
                'observed_at': self.wall_clock(),
            }

    def close(self):
        with self.lock:
            self.closed = True
            if self.active is not None:
                self.active[1].set()
        return self.done.wait(1.0)
