"""Audio playback helpers for the voice assistant."""

from __future__ import annotations

import contextlib
import io
import math
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path

from . import voice_logging as voice_logging


class PlaybackError(RuntimeError):
    pass


@dataclass
class PlaybackConfig:
    backend: str = "auto"  # "auto" | "pulse" | "alsa" | nazwa binarki
    alsa_device: str | None = None  # np. "plughw:1,0" (używane z mpg123/aplay)
    volume: int = 100  # informacyjne (regulacja systemowa)
    ding: dict[str, object] = field(default_factory=dict)


@dataclass
class PlaybackStream:
    process: subprocess.Popen[bytes]
    fmt: str
    backend: str
    accumulate: bool = False
    _buffer: bytearray | None = None
    _failed: bool = False

    def __post_init__(self) -> None:
        if self.accumulate:
            self._buffer = bytearray()

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        if self._buffer is not None:
            self._buffer.extend(chunk)
        if not self.process.stdin:
            self._failed = True
            raise PlaybackError("Player stdin unavailable")
        try:
            self.process.stdin.write(chunk)
            self.process.stdin.flush()
        except Exception as exc:  # pragma: no cover
            self._failed = True
            raise PlaybackError(f"Player write failed: {exc}") from exc

    def close(self, *, timeout: float = 20.0) -> tuple[bool, bytes | None, str | None]:
        if self.process.stdin:
            with contextlib.suppress(Exception):
                self.process.stdin.close()
        try:
            rc = self.process.wait(timeout=timeout)
        except Exception:  # pragma: no cover
            with contextlib.suppress(Exception):
                self.process.kill()
            rc = -1
        stderr_text = None
        if self.process.stderr:
            try:
                stderr_text = self.process.stderr.read().decode("utf-8", "ignore").strip()
            except Exception:
                stderr_text = None
        audio = bytes(self._buffer) if self._buffer is not None else None
        ok = rc == 0 and not self._failed
        return ok, audio, stderr_text


def _choose_player(backend: str) -> str | None:
    """Zwróć ścieżkę do binarki gracza na podstawie backendu."""
    if backend == "pulse":
        return shutil.which("paplay") or shutil.which("aplay")
    if backend == "alsa":
        return shutil.which("aplay")
    if backend == "auto":
        for cand in ("paplay", "aplay", "ffplay"):
            path = shutil.which(cand)
            if path:
                return path
        return None
    return shutil.which(backend)


def _build_cmd(player_path: str, tmp_path: str, fmt: str, alsa_device: str | None) -> list[str]:
    """Zbuduj komendę odtwarzacza dla podanej binarki (plik na dysku)."""
    base = os.path.basename(player_path)
    if base == "aplay":
        # aplay gra tylko WAV/RAW — nie używać z MP3
        if fmt.lower() != "wav":
            raise PlaybackError("aplay cannot play non-WAV formats")
        if alsa_device:
            return [player_path, "-q", "-D", alsa_device, tmp_path]
        return [player_path, "-q", tmp_path]
    if base == "ffplay":
        # ffplay bez GUI
        return [player_path, "-autoexit", "-nodisp", tmp_path]
    # paplay i inne – wystarczy ścieżka
    return [player_path, tmp_path]


def _iter_mpg123_commands(config: PlaybackConfig):
    """Przygotuj warianty komend mpg123 przez stdin (stream)."""
    path = shutil.which("mpg123")
    if not path:
        return []
    backend = (config.backend or "pulse").lower()
    order = []
    if backend in {"pulse", "alsa"}:
        order.append(backend)
    else:
        order.extend(["pulse", "alsa"])
    # rezerwa bez -o (auto)
    order.append("default")
    seen: set[str] = set()
    commands = []
    for item in order:
        if item in seen:
            continue
        seen.add(item)
        if item == "pulse":
            cmd = [path, "-q", "-o", "pulse", "-"]
        elif item == "alsa":
            cmd = [path, "-q", "-o", "alsa"]
            if config.alsa_device:
                cmd += ["-a", config.alsa_device]
            cmd.append("-")
        else:
            cmd = [path, "-q", "-"]
        commands.append((f"mpg123-{item}", cmd))
    return commands


def _iter_wav_commands(config: PlaybackConfig):
    commands = []
    backend = (config.backend or "auto").lower()
    aplay = shutil.which("aplay")
    paplay = shutil.which("paplay")

    if backend == "alsa":
        if aplay:
            cmd = [aplay, "-q"]
            if config.alsa_device:
                cmd += ["-D", config.alsa_device]
            cmd.append("-")
            commands.append(("aplay", cmd))
        if paplay:
            commands.append(("paplay", [paplay, "-"]))
    else:  # pulse lub auto
        if paplay:
            commands.append(("paplay", [paplay, "-"]))
        if aplay:
            cmd = [aplay, "-q"]
            if config.alsa_device:
                cmd += ["-D", config.alsa_device]
            cmd.append("-")
            commands.append(("aplay", cmd))
    return commands


def start_stream(
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    accumulate: bool = False,
) -> PlaybackStream | None:
    """Spróbuj otworzyć strumień odtwarzacza dla danego formatu."""
    logger = logger or voice_logging.get_logger("voice.playback")
    fmt = (fmt or "").lower()

    if fmt == "mp3":
        for backend, cmd in _iter_mpg123_commands(config):
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except FileNotFoundError:
                # przejdź do kolejnego wariantu zamiast przerywać całą próbę
                logger.debug("playback.stream.cmd_missing", backend=backend)
                continue
            except Exception as exc:  # pragma: no cover
                logger.warning("playback.stream.start_failed", backend=backend, error=str(exc))
                continue
            logger.debug("playback.stream.start", backend=backend, command=" ".join(cmd))
            return PlaybackStream(proc, fmt="mp3", backend=backend, accumulate=accumulate)
        return None

    if fmt == "wav":
        for backend, cmd in _iter_wav_commands(config):
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("playback.stream.start_failed", backend=backend, error=str(exc))
                continue
            logger.debug("playback.stream.start", backend=backend, command=" ".join(cmd))
            return PlaybackStream(proc, fmt="wav", backend=backend, accumulate=accumulate)
        return None

    return None


def _fallback_file_play(
    audio: bytes,
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger,
    *,
    blocking: bool,
):
    """Awaryjny tryb: zapisz do pliku i zagraj binarką odpowiednią dla formatu."""
    # 0) VOICE_PLAYER ma pierwszeństwo (może wskazywać mpg123/paplay etc.)
    env_player = os.getenv("VOICE_PLAYER")
    env_cmd: list[str] | None = shlex.split(env_player) if env_player else None

    # 1) wybierz domyślnego gracza po formacie
    if env_cmd:
        player_cmd = env_cmd
    else:
        if fmt.lower() == "mp3":
            path = shutil.which("mpg123") or shutil.which("ffplay")
            if not path:
                raise PlaybackError("No MP3 player available (need mpg123 or ffplay)")
            player_cmd = [path]
        elif fmt.lower() == "wav":
            path = _choose_player(config.backend)
            if not path:
                raise PlaybackError(f"No playback command for backend '{config.backend}'")
            player_cmd = [path]
        else:
            # inne formaty – spróbuj ffplay
            path = shutil.which("ffplay")
            if not path:
                raise PlaybackError(f"No player for format '{fmt}'")
            player_cmd = [path, "-autoexit", "-nodisp"]

    # 2) zapisz do pliku tymczasowego
    suffix = ".wav" if (fmt or "").lower() == "wav" else f".{fmt}" if fmt else ".bin"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(audio)
        tmp_path = tmp.name
    finally:
        tmp.close()

    # 3) dołóż parametry per gracz
    base = os.path.basename(player_cmd[0])
    if base == "aplay" and config.alsa_device:
        player_cmd = player_cmd + ["-q", "-D", config.alsa_device, tmp_path]
    elif base == "mpg123":
        # plikowa ścieżka (nie stdin)
        if (config.backend or "auto").lower() == "alsa" and config.alsa_device:
            player_cmd = player_cmd + ["-q", "-o", "alsa", "-a", config.alsa_device, tmp_path]
        elif (config.backend or "auto").lower() == "pulse":
            player_cmd = player_cmd + ["-q", "-o", "pulse", tmp_path]
        else:
            player_cmd = player_cmd + ["-q", tmp_path]
    elif base == "ffplay":
        player_cmd = player_cmd + ["-autoexit", "-nodisp", tmp_path]
    else:
        player_cmd = player_cmd + [tmp_path]

    logger.event("playback.start.fallback_file", command=" ".join(player_cmd))
    proc = subprocess.Popen(player_cmd)

    def _cleanup() -> None:
        rc = proc.wait()
        logger.event("playback.done", returncode=rc)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)

    if blocking:
        _cleanup()
        return proc.returncode == 0
    threading.Thread(target=_cleanup, daemon=True).start()
    return proc


def play_bytes(
    audio: bytes,
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    blocking: bool = True,
):
    """
    Odtwórz bajty audio. Preferuje strumieniowanie (stdin) dla MP3/WAV.
    Jeśli stream nieosiągalny — fallback do pliku tymczasowego.
    """
    logger = logger or voice_logging.get_logger("voice.playback")
    fmt = (fmt or "").lower()

    # 1) spróbuj trybu strumieniowego
    stream = start_stream(fmt, config, logger, accumulate=False)
    if stream:
        try:
            if blocking:
                stream.write(audio)
                ok, _, err = stream.close()
                if not ok and err:
                    logger.warning("playback.stream.error", backend=stream.backend, error=err)
                return ok
            else:

                def _bg():
                    try:
                        stream.write(audio)
                        stream.close()
                    except Exception as exc:  # pragma: no cover
                        logger.warning("playback.stream.bg_error", error=str(exc))

                threading.Thread(target=_bg, daemon=True).start()
                return stream.process
        except Exception as exc:  # pragma: no cover
            logger.warning("playback.stream.failed_write", error=str(exc))
            # przejdź do fallbacku plikowego

    # 2) fallback do pliku (pewnie brak mpg123/paplay)
    return _fallback_file_play(audio, fmt, config, logger, blocking=blocking)


def play_file(
    path: str | os.PathLike[str],
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    blocking: bool = True,
):
    with open(path, "rb") as fh:
        data = fh.read()
    fmt = Path(path).suffix.lstrip(".").lower() or "wav"
    return play_bytes(data, fmt, config, logger, blocking=blocking)


def play_ding(config: PlaybackConfig, logger: voice_logging.VoiceLogger | None = None) -> None:
    """
    Zagraj krótki „ding”.
    - Szanuje config.ding.enabled (jeśli podane).
    - Jeśli config.ding.path istnieje – odtwarza plik, inaczej generuje ton 880 Hz ~200 ms.
    - Wspiera config.ding.gain_db dla generowanego tonu.
    """
    logger = logger or voice_logging.get_logger("voice.playback")
    ding_cfg = config.ding or {}

    # enabled: domyślnie True; ustaw False aby wyłączyć
    enabled = ding_cfg.get("enabled")
    if isinstance(enabled, bool) and not enabled:
        logger.event("playback.ding.skip")
        return

    # jeśli jest ścieżka do pliku – odtwórz ją (bez zmiany głośności)
    path = ding_cfg.get("path") if isinstance(ding_cfg, dict) else None
    if isinstance(path, str) and os.path.exists(path):
        play_file(path, config, logger, blocking=False)
        return

    # generowany ton – uwzględnij gain_db
    gain_db = 0.0
    try:
        if "gain_db" in ding_cfg:
            gain_db = float(ding_cfg["gain_db"])  # np. -3.0
    except Exception:
        gain_db = 0.0

    logger.event("playback.ding.generate")
    # bazowa amplituda 0.25, skala z dB
    base_amp = 0.25
    scale = 10.0 ** (gain_db / 20.0)
    amplitude = max(0.0, min(1.0, base_amp * scale))
    audio = _tone_wav(duration=0.20, freq=880.0, sample_rate=16000, amplitude=amplitude)
    play_bytes(audio, "wav", config, logger, blocking=False)


# ───────────────────────────────────────────────────────────────────────────────
# Pomocnicze: generacja prostego tonu do dinga (WAV w pamięci)
# ───────────────────────────────────────────────────────────────────────────────


def _tone_wav(duration: float, freq: float, sample_rate: int = 16000, amplitude: float = 0.25) -> bytes:
    """Zwróć bajty WAV (mono, 16-bit) z prostym sinusem."""
    frame_count = max(1, int(duration * sample_rate))
    buf = bytearray()

    # obwiednia 5 ms start / 40 ms koniec – bez klików
    fade_in_frames = min(frame_count, int(0.005 * sample_rate))
    fade_out_frames = min(frame_count, int(0.040 * sample_rate))

    for i in range(frame_count):
        if i < fade_in_frames:
            env = (i + 1) / max(1, fade_in_frames)
        elif i >= frame_count - fade_out_frames:
            env = (frame_count - i) / max(1, fade_out_frames)
        else:
            env = 1.0

        s = math.sin(2 * math.pi * freq * (i / sample_rate))
        value = int(amplitude * env * s * 32767.0)
        buf.extend(value.to_bytes(2, "little", signed=True))

    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(buf))
    return bio.getvalue()
