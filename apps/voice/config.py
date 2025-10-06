from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

try:  # py>=3.11
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = ["load", "override_from_pairs", "unknown_keys", "_warn_unknown_keys"]

# ---------- ścieżki ----------


def _repo_root() -> Path:
    # .../apps/voice/config.py -> .../apps -> repo root
    return Path(__file__).resolve().parents[2]


def _config_dir() -> Path:
    # docelowo można podmienić na RIDER_CONFIG_DIR; tu trzymamy repo/config
    return _repo_root() / "config"


def _resolve_config_path(path: str | Path | None) -> Path:
    if path is None:
        return _config_dir() / "voice.toml"
    p = Path(path)
    return p if p.is_absolute() else (_config_dir() / p)


# ---------- narzędzia ----------


def _deep_set(dst: MutableMapping[str, Any], key_path: Iterable[str], value: Any) -> None:
    cur = dst
    parts = list(key_path)
    for k in parts[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]  # type: ignore[index]
    cur[parts[-1]] = value  # type: ignore[index]


def _deep_merge(a: MutableMapping[str, Any], b: Mapping[str, Any]) -> MutableMapping[str, Any]:
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_merge(a[k], v)  # type: ignore[index]
        else:
            a[k] = v  # type: ignore[index]
    return a


_JSON_LIKE = re.compile(r"""^\s*(\{.*\}|\[.*\])\s*$""", re.S)


def _parse_value(s: str) -> Any:
    t = s.strip()
    # bool / null
    low = t.lower()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none"}:
        return None
    # int / float / hex
    try:
        if t.startswith(("0x", "0X")):
            return int(t, 16)
        if "." in t:
            return float(t)
        return int(t)
    except ValueError:
        pass
    # JSON (list/dict/quoted string)
    if _JSON_LIKE.match(t) or (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        try:
            return json.loads(t)
        except Exception:
            pass
    return t  # fallback: string


# ---------- public API ----------


def override_from_pairs(*args: Any) -> dict[str, Any]:
    """
    Buduje słownik override z listy par 'k1.k2=value'.

    Obsługiwane wywołania:
      - override_from_pairs(pairs)
      - override_from_pairs(prefix, pairs)

    Przykład:
      override_from_pairs(["asr.backend=vosk", "tts.rate=1.1"])
      override_from_pairs("chat", ["transport=realtime", "max_tokens=120"])
    """
    if len(args) == 1:
        prefix: str | None = None
        pairs = args[0]
    elif len(args) == 2:
        prefix = str(args[0]) if args[0] is not None else None
        pairs = args[1]
    else:
        raise TypeError("override_from_pairs expects (pairs) or (prefix, pairs)")

    if isinstance(pairs, str):
        # pojedyncza para jako string
        pairs_iter: Iterable[str] = [pairs]
    else:
        pairs_iter = list(pairs)  # type: ignore[assignment]

    out: dict[str, Any] = {}
    for pair in pairs_iter:
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        keys = [p for p in k.strip().split(".") if p]
        if not keys:
            continue
        if prefix:
            keys = [prefix] + keys
        _deep_set(out, keys, _parse_value(v))
    return out


def unknown_keys(
    base: Mapping[str, Any],
    overrides: Mapping[str, Any],
    path: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    """
    Zwraca zbiór ścieżek kluczy (tuple), które nie istnieją w bazowym configu 'base'.
    Użycie: unknown_keys(base_known_schema, candidate_config). Sprawdzenie płytkie.
    """
    bad: set[tuple[str, ...]] = set()
    for k, v in overrides.items():
        if k not in base:
            bad.add((*path, k))
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            bad |= unknown_keys(base[k], v, (*path, k))  # type: ignore[index]
    return bad


def _warn_unknown_keys(candidate: Mapping[str, Any], known: Mapping[str, Any], stream=None) -> None:
    """
    Wypisz ostrzeżenia o nieznanych kluczach z 'candidate' względem 'known'.
    Format dokładnie jak oczekuje test: jedna linia na klucz, na STDOUT.
    """
    # policz nieznane: znane -> base, kandydat -> overrides
    bad = sorted(unknown_keys(known, candidate))
    if not bad:
        return
    if stream is None:
        import sys as _sys

        stream = _sys.stdout
    for parts in bad:
        path = ".".join(parts)
        print(f"WARNING: unknown config key '{path}'", file=stream)


def load(path: str | Path | None = None, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """
    Załaduj TOML (domyślnie config/voice.toml) i nałóż overrides (deep-merge).
    """
    cfg_path = _resolve_config_path(path)
    with cfg_path.open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    if overrides:
        _deep_merge(data, dict(overrides))
    return data
