"""SDK percentage interpretation without constructing a hardware adapter."""

import pytest

from drivers.xgo.adapter import XgoAdapter


@pytest.mark.parametrize("raw,expected", [(0, 0.0), (1, 0.01), (50, 0.5), (100, 1.0)])
def test_battery_byte_is_always_percent(raw, expected):
    adapter = object.__new__(XgoAdapter)
    adapter._read = lambda names: raw
    assert adapter.battery() == expected


@pytest.mark.parametrize("raw", [None, True, -1, 101, 0.8, float("nan"), float("inf")])
def test_unknown_battery_has_no_guessed_fallback(raw):
    adapter = object.__new__(XgoAdapter)
    adapter._read = lambda names: raw
    assert adapter.battery() is None
