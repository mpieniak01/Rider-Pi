"""Read Wi-Fi link state without changing the interface or exposing credentials."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

NET_ROOT = Path('/sys/class/net')
RFKILL_ROOT = Path('/sys/class/rfkill')
IP_COMMAND = '/usr/bin/ip'
COMMAND_TIMEOUT = 1.0


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _flag(path: Path) -> bool | None:
    value = _read(path)
    return {'0': False, '1': True}.get(value)


def _radio(net: Path) -> dict[str, bool | None]:
    phy = net / 'phy80211'
    if phy.exists():
        for entry in RFKILL_ROOT.glob('rfkill*'):
            if _read(entry / 'type') == 'wlan' and (entry / 'device').resolve() == phy.resolve():
                return {'soft_blocked': _flag(entry / 'soft'), 'hard_blocked': _flag(entry / 'hard')}
    return {'soft_blocked': None, 'hard_blocked': None}


def _output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT)


def get_wifi_state() -> dict[str, Any]:
    """Connected means an associated link with IPv4, not verified Internet access."""
    interface = 'wlan0'
    net = NET_ROOT / interface
    result: dict[str, Any] = {
        'interface': interface,
        'status': 'unknown',
        'carrier': None,
        'operstate': None,
        'addresses': [],
        'radio': {'soft_blocked': None, 'hard_blocked': None},
        'default_route': None,
        'gateway': None,
        'manager': 'dhcpcd',
        'autostart': None,
    }
    if not net.is_dir():
        result['status'] = 'missing'
        return result

    result.update(carrier=_flag(net / 'carrier'), operstate=_read(net / 'operstate'), radio=_radio(net))
    if any(value is True for value in result['radio'].values()):
        result['status'] = 'blocked'
    elif result['carrier'] is False:
        result['status'] = 'disconnected'
    try:
        output = _output(['systemctl', 'show', 'dhcpcd.service', '--property=UnitFileState'])
        state = next((line.partition('=')[2] for line in output.splitlines() if line.startswith('UnitFileState=')), '')
        if state:
            result['autostart'] = state == 'enabled'
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        addresses = json.loads(_output([IP_COMMAND, '-j', 'address', 'show', 'dev', interface]))
        if not isinstance(addresses, list):
            return result
        result['addresses'] = [
            address['local']
            for item in addresses
            for address in item.get('addr_info', [])
            if address.get('family') == 'inet' and address.get('scope') == 'global' and address.get('local')
        ]
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError, KeyError):
        # Missing tools or malformed output must not claim the link is disconnected.
        return result

    if result['status'] == 'unknown' and result['carrier'] is True:
        result['status'] = 'connected' if result['addresses'] else 'no_address'

    try:
        routes = json.loads(_output([IP_COMMAND, '-j', 'route', 'show', 'default', 'dev', interface]))
        if not isinstance(routes, list):
            return result
        # Older iproute2 omits "dev" when the command already filters by device.
        defaults = [
            route for route in routes if route.get('dst') == 'default' and route.get('dev', interface) == interface
        ]
        result['default_route'] = bool(defaults)
        result['gateway'] = next((route['gateway'] for route in defaults if route.get('gateway')), None)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        pass
    return result
