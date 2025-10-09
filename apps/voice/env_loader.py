from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable

DEFAULTS: dict[str, str] = {
    "OPENAI_BASE": "https://api.openai.com/v1",
    "OPENAI_REALTIME_ENDPOINT": ("wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"),
}

WHITELIST: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_ORG",
    "OPENAI_BASE",
    "OPENAI_REALTIME_ENDPOINT",
    "ALSA_CONFIG_PATH",
    "VOICE_CONFIG",
    "PYTHONUNBUFFERED",
    "VOICE_WS_LOG",
    "VOICE_WS_DUMP",
)


def _merge_defaults() -> None:
    """Uzupełnij brakujące wartości domyślne w os.environ."""
    for key, val in DEFAULTS.items():
        os.environ.setdefault(key, val)


def _source_profile_and_dump_env() -> dict[str, str]:
    """
    Uruchom loginowego basha, załaduj ~/.bash_profile (jeśli istnieje),
    a następnie zwróć środowisko jako dict tylko z kluczami z WHITELIST.
    """
    cmd = "bash -lc '[ -f ~/.bash_profile ] && source ~/.bash_profile >/dev/null 2>&1 || true; env -0'"
    out = subprocess.check_output(cmd, shell=True)  # nosec - kontrolowane polecenie
    result: dict[str, str] = {}

    for pair in out.split(b"\x00"):
        if not pair:
            continue
        kv = pair.split(b"=", 1)
        if len(kv) != 2:
            continue

        raw_key, raw_val = kv
        key = raw_key.decode("utf-8", "ignore")
        if key in WHITELIST:
            result[key] = raw_val.decode("utf-8", "ignore")

    return result


def ensure_env_from_bash_profile(keys: Iterable[str] | None = None) -> None:
    """
    Jeżeli wymagane zmienne nie są ustawione, spróbuj dociągnąć je z ~/.bash_profile.
    Zawsze na końcu uzupełnij DEFAULTS (nie nadpisując istniejących wartości).
    """
    wanted = set(keys or WHITELIST)
    has_all = all(os.environ.get(k) for k in wanted)
    if has_all:
        _merge_defaults()
        return

    try:
        sourced = _source_profile_and_dump_env()
        for key in wanted:
            if key not in os.environ and key in sourced:
                os.environ[key] = sourced[key]
    finally:
        _merge_defaults()
