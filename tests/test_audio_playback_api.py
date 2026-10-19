"""Raw WAV and common ownership tests use fake players and temporary locks."""

import io
import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask

from apps.compute.runners import wav_bytes
from services.api_core import http_contract, playback_api
from services.audio_playback import PlaybackManager


def audio():
    return wav_bytes(b'\0\0' * 320, 16000)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('RIDER_AGENT_TOKEN', 'unit-only-agent-token')
    calls = []
    manager = PlaybackManager(player=lambda *a, **k: calls.append((a, k)) or True, config=object())
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    playback_api.register(app, manager=manager)
    yield app.test_client(), manager, calls
    manager.close()


def headers(**changes):
    return {
        'Authorization': 'Bearer unit-only-agent-token',
        'Content-Type': 'audio/wav',
        'X-Rider-Playback-Id': 'playback-1',
        'X-Rider-Playback-TTL-Ms': '1000',
        'Accept': 'application/vnd.rider.api+json;version=1',
        **changes,
    }


def test_auth_and_raw_wav_reuse_shared_player_without_synthesis(client):
    http, _, calls = client
    denied = http.post('/api/voice/playback', data=audio(), headers={**headers(), 'Authorization': ''})
    assert denied.status_code == 401
    assert calls == []
    result = http.post('/api/voice/playback', data=audio(), headers=headers())
    assert result.status_code == 200
    assert result.json['meta']['contract_id'] == 'rider.audio'
    assert result.json['data']['state'] == 'played'
    assert result.json['data']['released'] is True
    assert calls[0][0][0] == audio()
    assert calls[0][0][1] == 'wav'
    assert calls[0][1]['sample_rate'] == 16000
    assert calls[0][1]['channels'] == 1
    assert isinstance(calls[0][1]['stop_event'], threading.Event)
    assert 'unit-only-agent-token' not in str(result.json)


@pytest.mark.parametrize(
    'key,value,status',
    [
        ('Content-Type', 'audio/mpeg', 415),
        ('X-Rider-Playback-Id', '../file', 400),
        ('X-Rider-Playback-TTL-Ms', '0', 400),
        ('X-Rider-Playback-TTL-Ms', '60001', 400),
        ('X-Rider-Playback-TTL-Ms', 'NaN', 400),
        ('X-Rider-Playback-TTL-Ms', '9' * 50, 400),
    ],
)
def test_invalid_metadata_never_opens_player(client, key, value, status):
    http, _, calls = client
    result = http.post('/api/voice/playback', data=audio(), headers=headers(**{key: value}))
    assert result.status_code == status
    assert not calls


@pytest.mark.parametrize('data', [b'not-wav', wav_bytes(b'\0\0' * 16000 * 16, 16000), b'x' * (2 * 1024 * 1024 + 1)])
def test_bad_audio_is_bounded_and_never_played(client, data):
    http, _, calls = client
    assert http.post('/api/voice/playback', data=data, headers=headers()).status_code in {400, 413}
    assert not calls


def test_duplicate_success_does_not_replay_sound(client):
    http, _, calls = client
    assert http.post('/api/voice/playback', data=audio(), headers=headers()).status_code == 200
    response = http.post('/api/voice/playback', data=audio(), headers=headers())
    assert response.status_code == 200
    assert response.json['data']['idempotent'] is True
    assert len(calls) == 1


def test_cancel_before_upload_blocks_late_player_start(client):
    http, _, calls = client
    cancelled = http.post(
        '/api/voice/playback/cancel',
        json={'playback_id': 'playback-1'},
        headers={'Authorization': 'Bearer unit-only-agent-token'},
    )
    assert cancelled.status_code == 200
    assert cancelled.json['released'] is True
    assert http.post('/api/voice/playback', data=audio(), headers=headers()).status_code == 409
    assert not calls


def test_cancel_auth_and_exact_fields(client):
    http, _, _ = client
    assert http.post('/api/voice/playback/cancel', json={'playback_id': 'x'}).status_code == 401
    assert (
        http.post(
            '/api/voice/playback/cancel',
            json={'playback_id': 'x', 'all': True},
            headers={'Authorization': 'Bearer unit-only-agent-token'},
        ).status_code
        == 400
    )


def test_expired_input_never_starts_player():
    calls = []
    manager = PlaybackManager(player=lambda *a, **k: calls.append(True), clock=lambda: 10, config=object())
    result, code = manager.execute(audio(), 'expired', 9)
    assert code == 409
    assert result['state'] == 'expired'
    assert not calls
    manager.close()


def test_single_active_cancel_releases_and_other_cancellation_does_not_stop_it():
    started = threading.Event()
    received = []

    def player(*_, stop_event, **__):
        started.set()
        assert stop_event.wait(2)
        return False

    manager = PlaybackManager(player=player, config=object())
    thread = threading.Thread(target=lambda: received.append(manager.execute(audio(), 'active', time.monotonic() + 5)))
    thread.start()
    assert started.wait(1)
    assert manager.execute(audio(), 'other', time.monotonic() + 5)[1] == 429
    unrelated = manager.cancel('other')
    assert unrelated['released'] is True
    assert manager.active[0] == 'active'
    cancelled = manager.cancel('active')
    thread.join(timeout=1)
    assert cancelled['released'] is True
    assert manager.active is None
    assert received[0][0]['state'] == 'cancelled'
    assert manager.close()


def test_off_cancels_player_and_refuses_late_start():
    started = threading.Event()

    def player(*_, stop_event, **__):
        started.set()
        assert stop_event.wait(2)
        return False

    manager = PlaybackManager(player=player, config=object())
    thread = threading.Thread(target=lambda: manager.execute(audio(), 'active', time.monotonic() + 5))
    thread.start()
    assert started.wait(1)
    assert manager.close()
    thread.join(timeout=1)
    assert manager.execute(audio(), 'late', time.monotonic() + 5)[1] == 409


def test_deadline_interrupts_active_player():
    def player(*_, stop_event, **__):
        assert stop_event.wait(1)
        return False

    manager = PlaybackManager(player=player, config=object())
    result, code = manager.execute(audio(), 'short', time.monotonic() + 0.02)
    assert code == 409
    assert result['state'] == 'expired'
    assert manager.active is None
    assert manager.close()


def test_common_stream_lock_covers_voice_cli_and_api(monkeypatch, tmp_path):
    from apps.voice.audio import playback

    monkeypatch.setenv('RIDER_AUDIO_LOCK_PATH', str(tmp_path / 'audio.lock'))
    processes = []

    def create(*_, **__):
        process = SimpleNamespace(
            stdin=io.BytesIO(), stdout=io.BytesIO(), stderr=io.BytesIO(), wait=lambda **_: 0, kill=lambda: None
        )
        processes.append(process)
        return process, 'alsa'

    monkeypatch.setattr(playback, '_start_playback_process', create)
    logger = SimpleNamespace(event=lambda *a, **k: None)
    first = playback.start_stream('wav', playback.PlaybackConfig(), logger)
    assert first is not None
    assert playback.start_stream('wav', playback.PlaybackConfig(), logger) is None
    assert len(processes) == 1
    first.close()
    assert processes[0].stdin.closed
    assert processes[0].stdout.closed
    assert processes[0].stderr.closed
    second = playback.start_stream('wav', playback.PlaybackConfig(), logger)
    assert second is not None
    second.close()
