"""Authenticated raw WAV playback; never loads a synthesis engine."""

from flask import current_app, jsonify, request

from apps.compute.client import ComputeError
from common.agent_control import authenticate
from services.audio_playback import PlaybackManager


def _validate_ttl(raw):
    if not 1 <= len(raw) <= 5 or not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 60000:
        raise ValueError('playback_ttl_invalid')


def _playback_error_status(error, exc):
    if error == 'agent_control_unconfigured':
        return 503
    if error == 'agent_auth_required':
        return 401
    return exc.status if isinstance(exc, ComputeError) and exc.status else 400


def play():
    manager = current_app.extensions['rider_audio_playback']
    received = manager.clock()
    try:
        authenticate(request.headers.get('Authorization', ''))
        if request.content_type != 'audio/wav':
            return jsonify({'ok': False, 'error': 'playback_wav_required'}), 415
        if request.content_length is None or not 0 < request.content_length <= 2 * 1024 * 1024:
            return jsonify({'ok': False, 'error': 'playback_input_size'}), 413
        raw = request.headers.get('X-Rider-Playback-TTL-Ms', '')
        _validate_ttl(raw)
        result, code = manager.execute(
            request.get_data(cache=False), request.headers.get('X-Rider-Playback-Id'), received + int(raw) / 1000
        )
        return jsonify(result), code
    except (ComputeError, ValueError) as exc:
        error = exc.code if isinstance(exc, ComputeError) else str(exc)
        return jsonify({'ok': False, 'error': error}), _playback_error_status(error, exc)


def cancel():
    try:
        authenticate(request.headers.get('Authorization', ''))
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'playback_id'}:
            raise ValueError('playback_cancel_fields')
        result = current_app.extensions['rider_audio_playback'].cancel(body['playback_id'])
        return jsonify(result), 202 if result.get('pending') else 200
    except ValueError as exc:
        error = str(exc)
        return jsonify({'ok': False, 'error': error}), (
            503 if error == 'agent_control_unconfigured' else 401 if error == 'agent_auth_required' else 400
        )


def register(app, *, manager=None):
    app.extensions['rider_audio_playback'] = manager or PlaybackManager()
    app.add_url_rule('/api/voice/playback', 'rider_audio_play', play, methods=['POST'])
    app.add_url_rule('/api/voice/playback/cancel', 'rider_audio_cancel', cancel, methods=['POST'])


def close(app):
    manager = app.extensions.get('rider_audio_playback')
    if manager is not None:
        return manager.close()
