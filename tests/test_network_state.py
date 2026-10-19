from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from services.api_core import network_state


@pytest.fixture
def wifi(tmp_path, monkeypatch):
    root = tmp_path / 'net'
    net = root / 'wlan0'
    phy = tmp_path / 'phy0'
    radio = tmp_path / 'rfkill' / 'rfkill0'
    net.mkdir(parents=True)
    phy.mkdir()
    radio.mkdir(parents=True)
    (net / 'phy80211').symlink_to(phy)
    (radio / 'device').symlink_to(phy)
    for path, value in (
        (net / 'carrier', '1'),
        (net / 'operstate', 'up'),
        (radio / 'type', 'wlan'),
        (radio / 'soft', '0'),
        (radio / 'hard', '0'),
    ):
        path.write_text(value)
    monkeypatch.setattr(network_state, 'NET_ROOT', root)
    monkeypatch.setattr(network_state, 'RFKILL_ROOT', radio.parent)
    data = {
        'addresses': [{'addr_info': [{'family': 'inet', 'scope': 'global', 'local': '192.0.2.14'}]}],
        'routes': [{'dst': 'default', 'dev': 'wlan0', 'gateway': '192.0.2.1'}],
        'manager': 'enabled',
    }

    def output(command):
        if command[0] == 'systemctl':
            return 'UnitFileState=' + data['manager']
        return json.dumps(data['addresses'] if 'address' in command else data['routes'])

    monkeypatch.setattr(network_state, '_output', output)
    return net, radio, data


def test_associated_link_with_ipv4_is_connected(wifi):
    state = network_state.get_wifi_state()
    assert state['status'] == 'connected'
    assert state['addresses'] == ['192.0.2.14']
    assert state['gateway'] == '192.0.2.1'
    assert state['default_route'] is True
    assert state['autostart'] is True


def test_old_dhcp_address_without_carrier_is_disconnected(wifi):
    net, _, _ = wifi
    (net / 'carrier').write_text('0')
    assert network_state.get_wifi_state()['status'] == 'disconnected'


@pytest.mark.parametrize('block', ['soft', 'hard'])
def test_radio_block_wins_over_old_address_and_carrier(wifi, block):
    _, radio, _ = wifi
    (radio / block).write_text('1')
    assert network_state.get_wifi_state()['status'] == 'blocked'


def test_associated_link_waiting_for_ip_is_not_connected(wifi):
    _, _, data = wifi
    data['addresses'] = [{'addr_info': [{'family': 'inet6', 'scope': 'link', 'local': 'fe80::1'}]}]
    assert network_state.get_wifi_state()['status'] == 'no_address'


def test_lan_connection_without_default_route_still_is_connected(wifi):
    _, _, data = wifi
    data['routes'] = []
    state = network_state.get_wifi_state()
    assert state['status'] == 'connected'
    assert state['default_route'] is False


def test_device_filtered_routes_on_bullseye_omit_the_dev_field(wifi):
    _, _, data = wifi
    data['routes'] = [{'dst': 'default', 'gateway': '192.0.2.1', 'protocol': 'dhcp', 'metric': 303}]
    state = network_state.get_wifi_state()
    assert state['default_route'] is True
    assert state['gateway'] == '192.0.2.1'


@pytest.mark.parametrize('failure', [FileNotFoundError(), subprocess.TimeoutExpired('ip', 1), ValueError('bad JSON')])
def test_probe_failure_is_unknown_not_disconnected(wifi, monkeypatch, failure):
    def broken(command):
        if command[0] == 'systemctl':
            return 'UnitFileState=enabled'
        raise failure

    monkeypatch.setattr(network_state, '_output', broken)
    assert network_state.get_wifi_state()['status'] == 'unknown'


def test_known_block_is_preserved_when_ip_tool_is_missing(wifi, monkeypatch):
    _, radio, _ = wifi
    (radio / 'soft').write_text('1')

    def missing(command):
        raise FileNotFoundError()

    monkeypatch.setattr(network_state, '_output', missing)
    assert network_state.get_wifi_state()['status'] == 'blocked'


def test_missing_interface_is_not_a_service_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(network_state, 'NET_ROOT', tmp_path)
    assert network_state.get_wifi_state()['status'] == 'missing'


def test_unreadable_carrier_is_unknown_even_with_ip(wifi):
    net, _, _ = wifi
    (net / 'carrier').unlink()
    assert network_state.get_wifi_state()['status'] == 'unknown'


def test_no_radio_metadata_does_not_invent_a_block(wifi):
    _, radio, _ = wifi
    (radio / 'device').unlink()
    state = network_state.get_wifi_state()
    assert state['status'] == 'connected'
    assert state['radio'] == {'soft_blocked': None, 'hard_blocked': None}


def test_runtime_only_enablement_does_not_claim_boot_autostart(wifi):
    _, _, data = wifi
    data['manager'] = 'enabled-runtime'
    assert network_state.get_wifi_state()['autostart'] is False


def test_read_only_commands_have_a_bounded_timeout(monkeypatch):
    def check(command, **kwargs):
        assert command == ['/usr/bin/ip', '-j', 'address', 'show', 'dev', 'wlan0']
        assert kwargs['timeout'] == 1.0
        assert kwargs['stderr'] == subprocess.DEVNULL
        return '[]'

    monkeypatch.setattr(network_state.subprocess, 'check_output', check)
    assert network_state._output(['/usr/bin/ip', '-j', 'address', 'show', 'dev', 'wlan0']) == '[]'
