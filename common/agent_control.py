"""Signed agent provenance for HTTP ingress and the sole motion executor."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re

BODY_FIELDS = frozenset(
    {
        'generation',
        'agent_epoch',
        'seq',
        'ts',
        'ttl_ms',
        'settings_revision',
        'request_id',
        'intent_id',
        'channel',
        'direction',
    }
)
CONSTANTS = {
    'source': 'agent',
    'execution_context': 'agent',
    'action': 'move',
    'mode': 'pulse',
    'device_settings': True,
}
SIGNED_FIELDS = BODY_FIELDS | CONSTANTS.keys()
RESOLVED_FIELDS = frozenset({'vx', 'yaw', 'duration'})
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
MANUAL_AGENT_GRACE_S = 0.5


def _token() -> str:
    token = os.getenv('RIDER_AGENT_TOKEN', '')
    if not token or len(token) > 4096 or '\n' in token or '\r' in token:
        raise ValueError('agent_control_unconfigured')
    return token


def authenticate(authorization: str) -> None:
    expected = 'Bearer ' + _token()
    if not isinstance(authorization, str) or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise ValueError('agent_auth_required')


def _validate_sequence_fields(body):
    if type(body['seq']) is not int or not 0 <= body['seq'] < 2**63:
        raise ValueError('agent_sequence_invalid')
    if type(body['ttl_ms']) is not int or not 1 <= body['ttl_ms'] <= 500:
        raise ValueError('agent_ttl_invalid')
    if type(body['settings_revision']) is not int or body['settings_revision'] < 0:
        raise ValueError('agent_settings_revision_invalid')


def validate_body(body: dict) -> None:
    if not isinstance(body, dict) or set(body) != BODY_FIELDS:
        raise ValueError('agent_payload_fields')
    for field in ('generation', 'agent_epoch', 'request_id', 'intent_id'):
        if not isinstance(body[field], str) or not IDENTIFIER.fullmatch(body[field]):
            raise ValueError('agent_identifier_invalid')
    _validate_sequence_fields(body)
    try:
        valid_time = type(body['ts']) in (int, float) and math.isfinite(body['ts']) and body['ts'] >= 0
    except OverflowError:
        valid_time = False
    if not valid_time:
        raise ValueError('agent_timestamp_invalid')
    if (
        not isinstance(body['channel'], str)
        or not isinstance(body['direction'], str)
        or (
            body['channel'] not in {'chat', 'voice'}
            or body['direction'] not in {'forward', 'backward', 'left', 'right'}
        )
    ):
        raise ValueError('agent_direction_or_channel_invalid')


def _digest(command: dict) -> str:
    body = {key: command[key] for key in BODY_FIELDS}
    validate_body(body)
    body['ts'] = float(body['ts'])
    encoded = json.dumps({**body, **CONSTANTS}, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hmac.new(_token().encode(), encoded, hashlib.sha256).hexdigest()


def signed_command(body: dict) -> dict:
    validate_body(body)
    command = {**body, **CONSTANTS}
    command['agent_signature'] = _digest(command)
    return command


def verify_command(command: dict, *, resolved=False) -> None:
    if not isinstance(command, dict) or set(command) != SIGNED_FIELDS | {'agent_signature'} | (
        RESOLVED_FIELDS if resolved and RESOLVED_FIELDS.issubset(command) else set()
    ):
        raise ValueError('agent_provenance_invalid')
    if any(type(command.get(key)) is not type(value) or command[key] != value for key, value in CONSTANTS.items()):
        raise ValueError('agent_provenance_invalid')
    signature = command.get('agent_signature')
    if not isinstance(signature, str) or len(signature) != 64 or not hmac.compare_digest(signature, _digest(command)):
        raise ValueError('agent_provenance_invalid')


def is_agent(command) -> bool:
    return isinstance(command, dict) and (
        command.get('source') == 'agent' or command.get('execution_context') == 'agent'
    )
