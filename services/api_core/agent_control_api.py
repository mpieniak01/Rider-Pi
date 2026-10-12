"""Private agent producer; hardware remains behind the shared executor gate."""

import time

from flask import jsonify, request

from common.agent_control import authenticate, signed_command
from services.control_commands import submit_control
from services.safety_contract import read_status


def state():
    return jsonify({'ok': True, 'safety': read_status(), 'server_time': time.time()})


def pulse():
    try:
        authenticate(request.headers.get('Authorization', ''))
        if request.content_length is None or not 0 < request.content_length <= 8192:
            return jsonify({'ok': False, 'error': 'agent_payload_size'}), 413
        command = signed_command(request.get_json(silent=True))
    except ValueError as exc:
        code = str(exc)
        return jsonify({'ok': False, 'error': code}), (
            503 if code == 'agent_control_unconfigured' else 401 if code == 'agent_auth_required' else 400
        )
    result, code = submit_control(command, allow_agent=True)
    return jsonify({**result, 'server_time': time.time()}), code


def register(app):
    app.add_url_rule('/api/control/agent/state', 'agent_control_state', state, methods=['GET'])
    app.add_url_rule('/api/control/agent/pulse', 'agent_control_pulse', pulse, methods=['POST'])
