"""The existing speaker lock is the only active-state authority, using fake time."""

import json
from types import SimpleNamespace

import pytest

from apps.voice.audio import ownership
from common.runtime_lock import exclusive


@pytest.fixture
def clock(monkeypatch, tmp_path):
    monkeypatch.setenv('RIDER_AUDIO_LOCK_PATH', str(tmp_path / 'audio.lock'))
    now = [10.0]
    monkeypatch.setattr(ownership, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_actual_lock_owner_and_short_playback_generation(clock):
    observer = ownership.PlaybackObserver(clock=lambda: clock[0])
    assert observer.snapshot() == ownership.PlaybackState()
    with ownership.own_playback():
        assert observer.snapshot().active
        with pytest.raises(TimeoutError):
            with ownership.own_playback():
                pytest.fail('second speaker admitted')
    first = observer.snapshot()
    assert not first.active and first.generation
    assert first.quiet_until == pytest.approx(10.35)
    with ownership.own_playback():
        pass  # Starts and ends entirely between observer polls.
    second = observer.snapshot()
    assert second.generation != first.generation and not second.active
    assert set(json.loads(observer.path.read_text())) == {'v', 'boot_id', 'generation', 'ended_at'}
    assert observer.fd is not None
    observer.close()
    assert observer.fd is None
    with pytest.raises(OSError, match='closed'):
        observer.snapshot()


def test_existing_empty_lock_and_unknown_writer_still_use_real_lock(clock):
    observer = ownership.PlaybackObserver(clock=lambda: clock[0])
    with exclusive(observer.path):
        assert observer.snapshot().active
    assert observer.snapshot() == ownership.PlaybackState()
    observer.close()


def test_released_owner_without_completion_has_one_bounded_drain(clock):
    observer = ownership.PlaybackObserver(clock=lambda: clock[0])
    observer.path.write_text(
        json.dumps({'v': 1, 'boot_id': observer.boot_id, 'generation': 'a' * 32, 'ended_at': None})
    )
    assert observer.snapshot().quiet_until == pytest.approx(10.35)
    clock[0] = 11
    assert observer.snapshot().quiet_until == pytest.approx(10.35)
    observer.close()


def test_previous_boot_cannot_extend_current_monotonic_drain(clock):
    observer = ownership.PlaybackObserver(clock=lambda: clock[0])
    observer.path.write_text(
        json.dumps({'v': 1, 'boot_id': 'previous-boot', 'generation': 'a' * 32, 'ended_at': 99999})
    )
    assert observer.snapshot() == ownership.PlaybackState()
    observer.close()


@pytest.mark.parametrize('record', ['{', 'x' * 1025, '[]', '{"v":2}', '{"v":1,"boot_id":"CURRENT"}'])
def test_corrupt_or_oversized_state_is_not_treated_as_idle(clock, record):
    observer = ownership.PlaybackObserver(clock=lambda: clock[0])
    observer.path.write_text(record.replace('CURRENT', observer.boot_id))
    with pytest.raises(ValueError):
        observer.snapshot()
    observer.close()


def test_replaced_lock_file_is_observed_without_leaking_previous_fd(clock):
    observer = ownership.PlaybackObserver(clock=lambda: clock[0])
    with ownership.own_playback():
        pass
    first = observer.snapshot()
    old_fd = observer.fd
    observer.path.rename(observer.path.with_suffix('.previous'))
    with ownership.own_playback():
        pass
    assert observer.snapshot().generation != first.generation
    # Descriptor number may be reused; its inode must follow the new lock.
    import os

    assert os.fstat(observer.fd).st_ino == observer.path.stat().st_ino
    assert old_fd is not None
    observer.close()


@pytest.mark.parametrize('raises', [False, True])
def test_failed_player_start_releases_shared_owner_and_records_completion(clock, monkeypatch, raises):
    from apps.voice.audio import playback

    observer = ownership.PlaybackObserver(clock=lambda: clock[0])

    def start(*_, **__):
        assert observer.snapshot().active
        if raises:
            raise RuntimeError('fake player unavailable')
        return None, 'fixture'

    monkeypatch.setattr(playback, '_start_playback_process', start)
    logger = SimpleNamespace(event=lambda *a, **k: None)
    if raises:
        with pytest.raises(RuntimeError, match='fake player unavailable'):
            playback.start_stream('wav', playback.PlaybackConfig(), logger)
    else:
        assert playback.start_stream('wav', playback.PlaybackConfig(), logger) is None
    state = observer.snapshot()
    assert not state.active and state.generation and state.quiet_until == pytest.approx(10.35)
    observer.close()
