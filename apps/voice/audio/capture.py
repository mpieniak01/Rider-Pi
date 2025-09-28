# apps/voice/audio/capture.py
from __future__ import annotations

import contextlib
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Final

from .. import voice_logging as voice_logging
from ..errors import CaptureError


@dataclass
class CaptureConfig:
    """
    Konfiguracja wejścia audio (ALSA/arecord RAW PCM).

    Pola:
      - backend: nazwa backendu, obecnie wspieramy "alsa"
      - device: urządzenie ALSA, np. "wm8960_in" (alias dsnoop) lub "plughw:wm8960soundcard,0"
      - sample_rate: próbkowanie w Hz (np. 16000)
      - channels: liczba kanałów (1=mono, 2=stereo)
      - frame_ms: długość ramki w milisekundach (np. 20)
      - buffer_seconds: dodatkowy bufor dla ALSA/arecord (sekundy, 0.0 ⇒ brak)
      - command: (opcjonalnie) program nagrywający (domyślnie "arecord")
      - extra_args: lista dodatkowych argumentów do arecord (np. ["--period-time","20000"])
      - sample_format: (opcjonalnie) format próbek przekazywany do arecord (-f),
                       np. "S16_LE" (domyślny), "S24_LE", "S32_LE".
                       Uwaga: downstream zakłada S16_LE dla obliczania frame_bytes,
                       dlatego domyślnie wymuszamy S16_LE na wyjściu arecord.
    """

    backend: str = "alsa"
    device: str = ""
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 20
    buffer_seconds: float = 0.0
    command: str | None = None
    extra_args: list[str] = field(default_factory=list)
    sample_format: str | None = None  # np. "S16_LE" / "S24_LE" / "S32_LE"

    # 16-bit PCM (S16_LE) → 2 bajty na próbkę
    BYTES_PER_SAMPLE: Final[int] = 2

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be > 0")
        if self.channels <= 0:
            raise ValueError("channels must be > 0")
        if self.frame_ms <= 0:
            raise ValueError("frame_ms must be > 0")
        if self.buffer_seconds < 0.0:
            self.buffer_seconds = 0.0

        # domyślne, sensowne urządzenie dla Rider-Pi (WM8960 dsnoop)
        if not self.device:
            # preferuj alias z ~/.asoundrc, jeśli istnieje
            self.device = "wm8960_in"

        # Domyślnie wymuszamy S16_LE (spójne z BYTES_PER_SAMPLE=2 i downstream)
        if self.sample_format is None:
            self.sample_format = "S16_LE"

    @property
    def frame_duration_s(self) -> float:
        return self.frame_ms / 1000.0

    @property
    def frame_samples(self) -> int:
        return int(self.sample_rate * self.frame_duration_s)

    @property
    def frame_bytes(self) -> int:
        # Liczymy rozmiar ramki dla S16_LE (2 bajty/próbka), niezależnie od
        # formatu źródłowego karty — bo arecord wymuszamy do S16_LE.
        return self.frame_samples * self.channels * self.BYTES_PER_SAMPLE

    @property
    def buffer_time_us(self) -> int:
        return int(self.buffer_seconds * 1_000_000)

    def bytes_for_ms(self, ms: int | float) -> int:
        seconds = float(ms) / 1000.0
        samples = int(self.sample_rate * seconds)
        return samples * self.channels * self.BYTES_PER_SAMPLE


class AudioCapture:
    """
    Stabilne przechwytywanie PCM przez ALSA (arecord → stdout).

    Użycie:
        cfg = CaptureConfig(...)
        with AudioCapture(cfg) as cap:
            for frame in cap.frames():
                ...

    Zwracane ramki mają dokładnie `cfg.frame_bytes` bajtów (S16_LE).
    """

    def __init__(
        self,
        config: CaptureConfig,
        logger: voice_logging.VoiceLogger | None = None,
        # Akceptuj (i ignoruj) niespodziewane kwargs z wyższych warstw,
        # m.in. sample_format podawany bezpośrednio do AudioCapture(...).
        **kwargs,
    ) -> None:
        # Jeżeli ktoś poda sample_format w kwargs — zapisz do config.sample_format,
        # ale i tak default to S16_LE (narzucony w CaptureConfig.__post_init__).
        sf = kwargs.pop("sample_format", None)
        if sf:
            try:
                # lekkie sanity — akceptuj tylko rodzinę Sxx_LE
                if not str(sf).upper().endswith("_LE"):
                    raise ValueError
                config.sample_format = str(sf).upper()
            except Exception:
                # ignoruj dziwne wartości; zostaw to co w config
                pass

        # reszta niespodziewanych kwargs jest ignorowana (brak wyjątku)
        self.config = config
        self.logger = logger or voice_logging.get_logger("voice.capture")
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._restart_guard = threading.Lock()

    # ---------------- internal helpers ----------------

    def _resolve_cmd_head(self) -> str:
        """Zwróć binarkę do nagrywania (config.command lub arecord z PATH)."""
        if self.config.command:
            cmd_head = shlex.split(self.config.command)[0]
            return shutil.which(cmd_head) or cmd_head
        path = shutil.which("arecord")
        if not path:
            raise CaptureError("arecord not found on PATH and no 'command' provided")
        return path

    def _build_cmd(self) -> list[str]:
        """Złóż kompletną komendę arecord do RAW PCM (wymuszamy S16_LE na wyjściu)."""
        path = self._resolve_cmd_head()

        # Ustal format wyjściowy: domyślnie S16_LE (zgodne z BYTES_PER_SAMPLE=2).
        fmt = (self.config.sample_format or "S16_LE").upper()
        # prosty whitelist — gdyby przyszło coś spoza rodziny Sxx_LE, wracamy do S16_LE
        if fmt not in {"S8", "S16_LE", "S24_LE", "S32_LE"}:
            fmt = "S16_LE"

        # arecord z RAW na stdout:
        cmd: list[str] = [
            path,
            "-q",
            "-t",
            "raw",
            "-f",
            fmt,  # wymuszamy format wyjściowy dla dalszego pipeline (zwykle S16_LE)
            "-c",
            str(max(1, int(self.config.channels))),
            "-r",
            str(self.config.sample_rate),
            "-D",
            self.config.device or "default",
        ]
        if self.config.buffer_time_us > 0:
            cmd += ["--buffer-time", str(self.config.buffer_time_us)]
        if self.config.extra_args:
            cmd += list(self.config.extra_args)
        cmd.append("-")  # stdout
        return cmd

    def _start_proc(self) -> subprocess.Popen:
        cmd = self._build_cmd()
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as exc:
            raise CaptureError(f"Failed to start capture command: {exc}") from exc
        self.logger.event("capture.proc.start", command=" ".join(cmd))
        return proc

    def _restart_proc(self, delay_s: float) -> subprocess.Popen | None:
        """Spróbuj łagodnie zrestartować arecord po problemie (XRUN/EOF)."""
        with self._restart_guard:
            if self._stop.is_set():
                return None
            self._kill_proc()
            time.sleep(max(0.01, delay_s))
            try:
                return self._start_proc()
            except Exception as exc:
                self.logger.event("capture.proc.restart_failed", error=str(exc))
                return None

    def _kill_proc(self) -> None:
        proc = self._proc
        self._proc = None
        if not proc:
            return
        with contextlib.suppress(Exception):
            if proc.stdout:
                proc.stdout.close()
        with contextlib.suppress(Exception):
            if proc.stderr:
                proc.stderr.close()
        with contextlib.suppress(Exception):
            proc.terminate()
        try:
            if proc.wait(timeout=1.5) is None:
                raise TimeoutError()
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()

    # ---------------- context manager ----------------

    def __enter__(self) -> AudioCapture:
        backend = (self.config.backend or "alsa").lower()
        if backend != "alsa":
            raise CaptureError(f"Unsupported capture backend: {backend}")
        # fallback do aliasu, jeśli nie podano device:
        if not self.config.device:
            self.config.device = "wm8960_in"
        self._proc = self._start_proc()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---------------- lifecycle ----------------

    def close(self) -> None:
        self._stop.set()
        self._kill_proc()
        self.logger.debug("capture.stop")

    # ---------------- frames iterator ----------------

    def frames(self) -> Iterator[bytes]:
        """
        Iterator ramek o rozmiarze dokładnie `frame_bytes`.
        Samodzielnie restartuje arecord w przypadku XRUN/EOF/EBUSY z backoffem.
        """
        fb = int(self.config.frame_bytes)
        backoff_s = 0.05  # początkowy backoff przy restarcie
        backoff_max = 1.00

        while not self._stop.is_set():
            proc = self._proc
            if not proc:
                # spróbuj wystartować (jeśli close() nie było wołane)
                proc = self._restart_proc(backoff_s)
                if not proc:
                    time.sleep(backoff_s)
                    backoff_s = min(backoff_max, backoff_s * 2.0)
                    continue
                self._proc = proc
                backoff_s = 0.05  # udany start – zresetuj backoff

            stdout = proc.stdout
            if not stdout:
                self.logger.warning("capture.stdout.missing")
                self._proc = self._restart_proc(backoff_s)
                backoff_s = min(backoff_max, backoff_s * 2.0)
                continue

            buf = bytearray()
            last_data_ts = time.time()

            while not self._stop.is_set():
                # ile nam brakuje do pełnej ramki?
                need = fb - len(buf)
                try:
                    chunk = stdout.read(need)
                except Exception as exc:
                    self.logger.event("capture.read.error", error=str(exc))
                    break

                if not chunk:
                    # może proces padł?
                    if proc.poll() is not None:
                        # spróbuj zebrać stderr
                        err_txt = None
                        if proc.stderr:
                            with contextlib.suppress(Exception):
                                err_txt = proc.stderr.read().decode("utf-8", "ignore").strip()
                        self.logger.event("capture.proc.exit", returncode=proc.returncode, stderr=err_txt)
                        break
                    # brak danych chwilowo – nie blokuj CPU
                    time.sleep(0.003)
                    # ostrzegaj o dłuższej ciszy bez bajtów (diagnostyka)
                    if (time.time() - last_data_ts) > 2.0:
                        self.logger.warning("capture.silence.timeout")
                        last_data_ts = time.time()
                    continue

                last_data_ts = time.time()
                buf.extend(chunk)
                if len(buf) >= fb:
                    out = bytes(buf[:fb])
                    del buf[:fb]
                    yield out

            # wyszliśmy z pętli czytania – spróbuj restartu jeśli nie jest zatrzymane
            if self._stop.is_set():
                break
            self._proc = self._restart_proc(backoff_s)
            backoff_s = min(backoff_max, backoff_s * 2.0)

        return
