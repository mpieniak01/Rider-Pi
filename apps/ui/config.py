from __future__ import annotations

import os
import pathlib
from typing import Any

# Python 3.11: tomllib w stdlib; na 3.9/3.10: tomli z PyPI
try:
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except Exception:
        tomllib = None  # type: ignore

# ROOT projektu = katalog główny repo (…/robot)
# Ten plik jest w: apps/ui/face/config.py  → repo root = parents[3]
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "apps" / "ui" / "face" / "face.toml"


def _as_str_dict(d: dict[str, Any]) -> dict[str, str]:
    """Spłaszcz i zamień wartości na str (tylko proste klucze typu 'FACE_*')."""
    flat: dict[str, str] = {}

    def walk(prefix: str, obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}{k}." if prefix else f"{k}.", v)
        else:
            # pozwalamy tylko na bezpośrednie klucze ENV w korzeniu TOML
            pass

    # Prosty wariant: bierzemy tylko klucze z korzenia, które wyglądają jak nazwy ENV
    for k, v in d.items():
        if isinstance(k, str) and k.isupper():  # np. FACE_IDLE_BLINK_SEC, itp.
            flat[k] = str(v)
    return flat


def load_config(path: str | None = None) -> dict[str, str]:
    """
    Wczytaj config TOML i zwróć mapę {ENV_KEY: "value"}.
    Priorytet ścieżek:
      1) `path` jeśli podana
      2) ENV FACE_CONFIG
      3) domyślnie: robot/config/face.toml
    """
    cfg_path: pathlib.Path
    if path:
        cfg_path = pathlib.Path(path).expanduser()
    else:
        env_p = os.getenv("FACE_CONFIG")
        cfg_path = pathlib.Path(env_p).expanduser() if env_p else DEFAULT_CONFIG_PATH

    if not cfg_path.exists():
        # brak pliku — zwracamy pustą mapę, nic nie ustawiamy
        return {}

    if tomllib is None:
        raise RuntimeError(
            "Brak tomllib/tomli — zainstaluj: pip3 install tomli (dla Pythona < 3.11)."
        )

    with cfg_path.open("rb") as f:
        data = tomllib.load(f)

    return _as_str_dict(data or {})


def apply_env_from_config(env_map: dict[str, str]) -> None:
    """Ustaw zmienne środowiskowe na podstawie mapy z load_config()."""
    for k, v in env_map.items():
        # Nie nadpisuj, jeśli już ustawione w procesie (pozwala na szybkie testy).
        if k not in os.environ:
            os.environ[k] = v
