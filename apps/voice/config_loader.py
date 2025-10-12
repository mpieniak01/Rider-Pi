from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

try:
    import tomllib  # py3.11+
except Exception:  # py3.9/3.10
    import tomli as tomllib  # type: ignore


# ========================== Public API (oczekiwane przez testy) ==========================


class ValidationError(Exception):
    pass


class FieldSchema(NamedTuple):
    # Testy tworzą FieldSchema(type=str, required=True)
    type: type[Any]
    required: bool


class ConfigSchema:
    """Publiczny, test-friendly wrapper na schemat.

    Testy mogą:
      - sprawdzać sekcje: 'capture' in ConfigSchema()
      - pobierać zestawy kluczy: ConfigSchema()['capture']
      - wołać .keys() lub używać .sections
      - modyfikować .sections jak dict (np. dodawać wymagane pola)
    """

    def __init__(self, data: dict[str, set[str]] | None = None) -> None:
        # Głęboka kopia wartości setów, aby uniknąć współdzielenia obiektów między instancjami
        self.data: dict[str, set[str]] = (
            {k: set(v) for k, v in SCHEMA.items()} if data is None else {k: set(v) for k, v in data.items()}
        )
        # Mapa: nazwa_sekcji -> { nazwa_pola -> FieldSchema }
        self._sections: dict[str, dict[str, FieldSchema]] = {sec: {} for sec in self.data.keys()}

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def __getitem__(self, key: str) -> set[str]:
        return self.data[key]

    def keys(self):
        return self.data.keys()

    @property
    def sections(self) -> dict[str, dict[str, FieldSchema]]:
        # Zwracamy słownik modyfikowalny (testy dopisują do niego pola wymagane)
        return self._sections


# ============================== Wewnętrzna definicja schematu =============================

ALLOWED_HOTWORD_ENGINES = {"porcupine", "ptt", "vosk", "none"}

# aliasy kluczy: pozwalamy używać historycznych nazw w TOML
# (mapujemy STARE -> NOWE, aby wszędzie w kodzie używać sample_*)
KEY_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    ("capture", "rate"): ("capture", "sample_rate"),
    ("capture", "format"): ("capture", "sample_format"),
}

# znane sekcje/klucze
SCHEMA: dict[str, set[str]] = {
    "capture": {"device", "sample_rate", "channels", "sample_format"},
    "playback": {"backend", "device", "volume"},
    "asr": {"backend", "model", "language"},
    "chat": {"backend", "model", "language", "system_prompt"},
    "tts": {"backend", "model", "format", "voice"},
    "nlu": {"backend", "chat_threshold", "llm_model", "command_keywords"},
    "hotword": {"enabled", "engine"},
    "stream": {
        "protocol",
        "endpoint",
        "auth",
        "chunk_ms",
        "server_vad",
        "turn_end_silence_ms",
        "max_turn_ms",
        "send_partials",
        "barge_in",
    },
    "ptt": {"commit_on_stop", "silence_ms", "max_turn_ms"},
    "files": {"input_wav", "output_wav"},
    "logging": {"level", "json", "sink"},
    "compat": {"allow_unknown_keys", "sample_rates"},
    # dla testu ścieżek względnych
    "save_audio": {"enabled", "dir"},
    # UŻYWANE PRZEZ svc_file.py – pełny zestaw
    "service": {
        "beep",
        "beep_delay_ms",
        "beep_pause_ms",
        "mic_open_delay_ms",
        "pre_speech_wait_ms",
        "no_speech_timeout_ms",
        "min_capture_ms",
        "post_tts_mute_ms",
        "save_audio",
        "recordings_dir",
        "silence_rms_gate",
    },
    "vad": {
        "mode",
        "frame_ms",
        "tail_ms",
        "energy_gate_dbfs",
        "max_len_ms",
    },
    # dodatkowe sekcje wymagane przez testy obecności
    "turn": set(),
}

# Dopuszczalne backendy per sekcja (wystarczające do testów)
ALLOWED_BACKENDS_PER_SECTION: dict[str, set[str]] = {
    "asr": {"openai"},
    "chat": {"openai", "google"},
    "tts": {"openai"},
    "nlu": {"passthrough", "dummy", "openai"},
    "playback": {"aplay"},
}


# =================================== Utilsy ===================================


def _deep_merge(a: dict[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = _deep_merge(dict(out[k]), v)  # type: ignore[index]
        else:
            out[k] = v
    return out


def _apply_aliases(d: dict[str, Any]) -> dict[str, Any]:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in d.items()}
    for (sec, old_key), (sec2, new_key) in KEY_ALIASES.items():
        if sec in out and isinstance(out[sec], dict) and old_key in out[sec]:
            if sec2 in out and isinstance(out[sec2], dict) and new_key not in out[sec2]:
                out[sec2][new_key] = out[sec][old_key]
            elif sec2 == sec and new_key not in out[sec]:
                out[sec][new_key] = out[sec][old_key]
            del out[sec][old_key]
    return out


def _resolve_relative_paths(d: dict[str, Any], base: Path) -> dict[str, Any]:
    """Zamienia ścieżki względne na absolutne względem katalogu pliku TOML."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in d.items()}

    # save_audio.dir
    sa = out.get("save_audio")
    if isinstance(sa, dict) and isinstance(sa.get("dir"), str):
        p = Path(sa["dir"])
        if not p.is_absolute():
            out["save_audio"]["dir"] = str((base / p).resolve())

    # service.recordings_dir
    svc = out.get("service")
    if isinstance(svc, dict) and isinstance(svc.get("recordings_dir"), str):
        p = Path(svc["recordings_dir"])
        if not p.is_absolute():
            out["service"]["recordings_dir"] = str((base / p).resolve())

    # files.input_wav/output_wav
    files = out.get("files")
    if isinstance(files, dict):
        for key in ("input_wav", "output_wav"):
            v = files.get(key)
            if isinstance(v, str):
                pv = Path(v)
                if not pv.is_absolute():
                    out["files"][key] = str((base / pv).resolve())

    return out


def _suggest(section: str, key: str, *, effective_schema: dict[str, set[str]]) -> str | None:
    """Zwraca sugestię literówki dla nieznanego klucza w danej sekcji."""
    import difflib

    allowed = effective_schema.get(section, set())
    if not allowed:
        return None
    best = difflib.get_close_matches(key, list(allowed), n=1, cutoff=0.6)
    return best[0] if best else None


def _mask_core_value(v: Any, *, keep_tail: int) -> Any:
    # bazowe maskowanie "wartości", bez kontekstu klucza
    if isinstance(v, str) and v.startswith("env:"):
        env_key = v.split(":", 1)[1]
        raw = os.environ.get(env_key, "")
        if not raw:
            return v
        tail = raw[-keep_tail:] if keep_tail > 0 else ""
        return f"env:{'*' * max(0, len(raw) - keep_tail)}{tail}"
    if isinstance(v, str) and (len(v) > keep_tail + 2) and ("sk-" in v.lower()):
        tail = v[-keep_tail:]
        return f"{'*' * (len(v) - keep_tail)}{tail}"
    if isinstance(v, list):
        return [_mask_core_value(x, keep_tail=keep_tail) for x in v]
    if isinstance(v, dict):
        return {kk: _mask_core_value(vv, keep_tail=keep_tail) for kk, vv in v.items()}
    return v


def _mask_secrets(d: dict[str, Any], *, keep_tail: int = 4) -> dict[str, Any]:
    """Maskuje wartości sekretów.

    Obsługa:
      - stringi zaczynające się od 'env:VAR' → pobierz z os.environ i zamaskuj,
      - surowe pola znane: 'api_key', 'auth', 'token', 'secret', 'password' → maskuj,
      - ciągi przypominające klucze (np. 'sk-...') → maskuj.
    """
    secret_keys = {"api_key", "auth", "token", "secret", "password"}

    out: dict[str, Any] = {}
    for k, v in d.items():
        if k.lower() in secret_keys and isinstance(v, str):
            # Top-level znany sekret
            tail = v[-keep_tail:] if keep_tail > 0 else ""
            out[k] = f"{'*' * max(0, len(v) - keep_tail)}{tail}"
        elif isinstance(v, dict):
            # Zagnieżdżone dict – maskuj rekurencyjnie, ale również klucze sekretów
            nested: dict[str, Any] = {}
            for kk, vv in v.items():
                if kk.lower() in secret_keys and isinstance(vv, str):
                    tail = vv[-keep_tail:] if keep_tail > 0 else ""
                    nested[kk] = f"{'*' * max(0, len(vv) - keep_tail)}{tail}"
                else:
                    nested[kk] = _mask_core_value(vv, keep_tail=keep_tail)
            out[k] = nested
        else:
            out[k] = _mask_core_value(v, keep_tail=keep_tail)

    return out


def mask_secrets(d: dict[str, Any], *, keep_tail: int = 4) -> dict[str, Any]:
    """Publiczny alias wymagany przez testy."""
    return _mask_secrets(d, keep_tail=keep_tail)


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if v is None:
        return '""'
    return '"' + str(v).replace('"', '\\"') + '"'


def print_effective_config(config: dict[str, Any], mask: bool = True) -> None:
    """Wypisz końcową konfigurację jako TOML (sekcja-per-dict)."""
    data = _mask_secrets(config) if mask else config
    lines: list[str] = []
    for k in sorted(data.keys()):
        v = data[k]
        if isinstance(v, dict):
            lines.append(f"[{k}]")
            for kk in sorted(v.keys()):
                vv = v[kk]
                lines.append(f"{kk} = {_toml_value(vv)}")
            lines.append("")
        else:
            lines.append(f"{k} = {_toml_value(v)}")
    sys.stdout.write("\n".join(lines).rstrip() + "\n")


# ===================================== Loader =====================================


@dataclass
class ConfigLoader:
    lenient: bool = False  # fail-fast domyślnie
    schema: ConfigSchema | None = None  # pozwala testom wstrzyknąć wymagane pola

    def __post_init__(self) -> None:
        # testy oczekują listy KROTEK
        self.unknown_keys: list[tuple[str, str]] = []
        self.validation_errors: list[str] = []
        # schema-injected required fields
        self._req_sections: dict[str, dict[str, FieldSchema]] = self.schema.sections if self.schema is not None else {}
        # efektywny schemat (wbudowany + dostarczony)
        self._effective_schema: dict[str, set[str]] = {k: set(v) for k, v in SCHEMA.items()}
        if self.schema is not None:
            for sec, keys in self.schema.data.items():
                if sec in self._effective_schema:
                    self._effective_schema[sec] = set(self._effective_schema[sec]) | set(keys)
                else:
                    self._effective_schema[sec] = set(keys)

    def _resolve_path(self, path: str | Path | None) -> Path:
        if path is None:
            raise ValidationError("Config path is required")
        p = Path(path)
        if p.is_absolute():
            if not p.exists():
                raise ValidationError(f"Config file not found: {p}")
            return p

        # Ścieżka względna: najpierw sprawdź tę, którą podał użytkownik
        p_user = (Path.cwd() / p).resolve()
        if p_user.exists():
            return p_user

        # Fallback: standardowe położenie repo/config/<file>
        repo_root = Path.cwd()
        default = (repo_root / "config" / p.name).resolve()
        if default.exists():
            return default

        raise ValidationError(f"Config file not found: {p_user}")

    def _format_validation_errors(self) -> str:
        parts: list[str] = ["Configuration validation failed:"]
        if self.unknown_keys:
            parts.append("\nUnknown keys:")
            for sec, key in sorted(self.unknown_keys):
                maybe = _suggest(sec, key, effective_schema=self._effective_schema)
                if maybe:
                    parts.append(f"  - {sec}.{key} (Did you mean '{maybe}'?)")
                else:
                    parts.append(f"  - {sec}.{key}")
        if self.validation_errors:
            parts.append("\nValidation errors:")
            for e in self.validation_errors:
                parts.append(f"  - {e}")
        return "\n".join(parts)

    def _warn_or_err_unknown(self, section: str, key: str) -> None:
        self.unknown_keys.append((section, key))

    def _validate(self, data: dict[str, Any]) -> None:
        self.unknown_keys.clear()
        self.validation_errors.clear()

        # pozwól wyłączyć błąd dla nieznanych kluczy
        allow_unknown = bool(isinstance(data.get("compat"), dict) and data["compat"].get("allow_unknown_keys") is True)

        def _mark_unknown(section: str, key: str) -> None:
            if not allow_unknown:
                self._warn_or_err_unknown(section, key)

        # --- sekcje nieznane (wg efektywnego schematu) ---
        for section in data.keys():
            if section not in self._effective_schema:
                _mark_unknown(section, "<section>")

        # --- weryfikacja kluczy w znanych sekcjach ---
        for section, allowed in self._effective_schema.items():
            if section not in data:
                continue
            sec_data = data[section]
            if not isinstance(sec_data, dict):
                self.validation_errors.append(f"Section '{section}' must be a table")
                continue
            for key in sec_data.keys():
                if key not in allowed:
                    _mark_unknown(section, key)

        # --- Reguły wartości ---
        cap = data.get("capture", {}) if isinstance(data.get("capture"), dict) else {}
        if "channels" in cap and cap["channels"] not in (1, 2):
            self.validation_errors.append("Field 'capture.channels' must be one of [1, 2]")
        if "sample_rate" in cap and cap["sample_rate"] not in (16000, 22050, 24000, 44100, 48000):
            self.validation_errors.append(
                "Field 'capture.sample_rate' must be one of [16000, 22050, 24000, 44100, 48000]"
            )
        if "sample_format" in cap and not isinstance(cap["sample_format"], str):
            self.validation_errors.append("Field 'capture.sample_format' must be a string (e.g., 'S16_LE')")

        pb = data.get("playback", {}) if isinstance(data.get("playback"), dict) else {}
        if "volume" in pb:
            vol = pb["volume"]
            if not isinstance(vol, int):
                self.validation_errors.append("Field 'playback.volume' must be an integer")
            elif vol > 100:
                self.validation_errors.append("Field 'playback.volume' must be <= 100")
            elif vol < 0:
                self.validation_errors.append("Field 'playback.volume' must be >= 0")

        # Backend: dozwolone wartości (jeśli mamy reguły dla danej sekcji)
        for section, allowed_backends in ALLOWED_BACKENDS_PER_SECTION.items():
            sec = data.get(section, {})
            if isinstance(sec, dict) and "backend" in sec:
                backend = sec["backend"]
                if isinstance(backend, str) and backend not in allowed_backends:
                    self.validation_errors.append(
                        f"Field '{section}.backend' must be one of {sorted(allowed_backends)}"
                    )

        hot = data.get("hotword", {}) if isinstance(data.get("hotword"), dict) else {}
        engine = hot.get("engine")
        if engine is not None and engine not in ALLOWED_HOTWORD_ENGINES:
            self.validation_errors.append(
                f"Field 'hotword.engine' must be one of {sorted(ALLOWED_HOTWORD_ENGINES)}, got '{engine}'"
            )

        # Wymagane pola z wstrzykniętego schema (jeśli podano)
        if self._req_sections:
            for section, fields in self._req_sections.items():
                if not fields:
                    continue
                sec_data = data.get(section, {})
                for field_name, meta in fields.items():
                    if meta.required:
                        if not isinstance(sec_data, dict) or field_name not in sec_data:
                            self.validation_errors.append(f"Missing required field '{section}.{field_name}'")

        # fail-fast gdy są błędy
        if not self.lenient and (self.unknown_keys or self.validation_errors):
            raise ValidationError(self._format_validation_errors())

    def load(
        self,
        path: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        toml_dir: Path | None = None,
    ) -> dict[str, Any]:
        config_path = self._resolve_path(path)
        base_dir = toml_dir or config_path.parent

        with config_path.open("rb") as f:
            data = tomllib.load(f)

        if overrides:
            data = _deep_merge(data, dict(overrides))

        data = _apply_aliases(data)
        data = _resolve_relative_paths(data, base_dir)

        self._validate(data)
        return data


def load_and_validate(
    path: str | Path,
    overrides: Mapping[str, Any] | None = None,
    *,
    lenient: bool = False,
) -> dict[str, Any]:
    loader = ConfigLoader(lenient=lenient)
    return loader.load(path, overrides)
