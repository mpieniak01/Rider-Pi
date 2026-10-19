import io
import subprocess

import pytest

from apps.voice.audio.playback import PlaybackStream


@pytest.mark.parametrize("timed_out", [False, True])
def test_close_releases_player_pipes_and_bounds_kill_wait(monkeypatch, timed_out):
    class IdleThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return False

    class Process:
        def __init__(self):
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(b"output")
            self.stderr = io.BytesIO(b"error")
            self.waits = []
            self.killed = False

        def wait(self, timeout):
            self.waits.append(timeout)
            if timed_out and not self.killed:
                raise subprocess.TimeoutExpired("fixture-player", timeout)
            return 0

        def kill(self):
            self.killed = True

    monkeypatch.setattr("apps.voice.audio.playback.threading.Thread", IdleThread)
    process = Process()
    stream = PlaybackStream(process, "wav", "fixture")
    success, output, error = stream.close(timeout=0.1)
    assert success is (not timed_out)
    assert (output, error) == (b"output", "error")
    assert process.stdin.closed
    assert process.stdout.closed
    assert process.stderr.closed
    assert process.waits == ([0.1, 1.0] if timed_out else [0.1])
    assert stream._closer_stop.is_set()
