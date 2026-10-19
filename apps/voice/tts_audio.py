"""PCM/WAV conversion and decoding shared by the TTS backends."""

from __future__ import annotations

import audioop
import io
import math
import wave

from . import voice_logging


def _is_wav(b: bytes) -> bool:
    return len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"


def _wrap_wav(pcm: bytes, sr: int, ch: int, sw: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(sw)
        wf.setframerate(int(sr))
        wf.writeframes(pcm)
    return buf.getvalue()


def _read_wav(b: bytes) -> tuple[bytes, int, int, int]:
    with wave.open(io.BytesIO(b), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    return pcm, sr, ch, sw


def _fade_in_out(pcm: bytes, sr: int, ch: int, ms_in: int = 5, ms_out: int = 40) -> bytes:
    """Delikatny fade-in/out, by uniknąć „pyknięć”. Operuje na 16-bit mono/stereo."""
    if not pcm or ch not in (1, 2) or len(pcm) < 4:
        return pcm
    n_samples_per_channel = len(pcm) // (2 * ch)
    if n_samples_per_channel == 0:
        return pcm
    import array

    a = array.array("h")
    a.frombytes(pcm)
    # fade-in
    n_in = min(n_samples_per_channel, int(sr * ms_in / 1000))
    for i in range(n_in):
        scale = (i + 1) / max(1, n_in)
        if ch == 1:
            a[i] = int(a[i] * scale)
        else:
            a[2 * i] = int(a[2 * i] * scale)
            a[2 * i + 1] = int(a[2 * i + 1] * scale)
    # fade-out
    n_out = min(n_samples_per_channel, int(sr * ms_out / 1000))
    for j in range(n_out):
        scale = j / max(1, n_out)
        idx_in_channel = n_samples_per_channel - 1 - j
        if ch == 1:
            a[idx_in_channel] = int(a[idx_in_channel] * scale)
        else:
            a[2 * idx_in_channel] = int(a[2 * idx_in_channel] * scale)
            a[2 * idx_in_channel + 1] = int(a[2 * idx_in_channel + 1] * scale)
    return a.tobytes()


def _normalize_16bit(pcm: bytes, target_peak: int = 30000, extra_gain: float = 1.0) -> bytes:
    """
    Prosta normalizacja: skaluje tak, by pik był ~target_peak,
    potem stosuje VOICE_GAIN (extra_gain). Zabezpiecza przed clippingiem.
    """
    if not pcm:
        return pcm
    import array

    a = array.array("h")
    a.frombytes(pcm)
    peak = max((abs(x) for x in a), default=1)
    gain = min(10.0, (target_peak / max(1, peak)) * float(extra_gain))
    if abs(gain - 1.0) < 1e-3:
        return pcm
    for i, v in enumerate(a):
        a[i] = int(max(-32768, min(32767, v * gain)))
    return a.tobytes()


def _decode_mp3_to_wav(audio_bytes: bytes, logger: voice_logging.VoiceLogger) -> bytes | None:
    """
    Spróbuj zdekodować MP3 → WAV narzędziami systemowymi (ffmpeg/mpg123).
    Zwraca WAV lub None (gdy brak narzędzi albo dekoder zawiedzie).
    """
    import shutil
    import subprocess

    if shutil.which("ffmpeg"):
        try:
            p = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    "pipe:0",
                    "-f",
                    "wav",
                    "pipe:1",
                ],
                input=audio_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            if _is_wav(p.stdout):
                return p.stdout
        except Exception as e:
            logger.event("tts.decode.ffmpeg_failed", extra={"data": str(e)})
    if shutil.which("mpg123"):
        try:
            p = subprocess.run(
                ["mpg123", "-q", "-w", "-", "-"],
                input=audio_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            if _is_wav(p.stdout):
                return p.stdout
        except Exception as e:
            logger.event("tts.decode.mpg123_failed", extra={"data": str(e)})
    return None


def _resample_to(pcm: bytes, in_sr: int, in_ch: int, target_sr: int, target_ch: int) -> tuple[bytes, int, int]:
    """
    Resample PCM using audioop. Zwraca (pcm_bytes, new_sr, new_ch).
    Wymaga 16-bit (sw=2).
    """
    if in_sr == target_sr and in_ch == target_ch:
        return pcm, in_sr, in_ch

    pcm_out = pcm
    sr_out, ch_out = in_sr, in_ch

    # Krok 1: Resample kanałów
    try:
        if target_ch == 2 and in_ch == 1:
            pcm_out = audioop.tostereo(pcm_out, 2, 1, 1)
            ch_out = 2
        elif target_ch == 1 and in_ch == 2:
            pcm_out = audioop.tomono(pcm_out, 2, 0.5, 0.5)
            ch_out = 1
    except audioop.error:
        # Błąd konwersji kanałów, kontynuuj z oryginałem
        pcm_out = pcm
        ch_out = in_ch

    # Krok 2: Resample częstotliwości
    try:
        if sr_out != target_sr:
            pcm_out, _ = audioop.ratecv(pcm_out, 2, ch_out, sr_out, target_sr, None)
            sr_out = target_sr
    except audioop.error as e:
        # Jeśli konwersja się nie uda, zwróć to co mamy (zmienione kanały, stara stopa)
        if "not supported" in str(e):
            return pcm_out, sr_out, ch_out
        raise e

    return pcm_out, sr_out, ch_out


def _append_tail(pcm: bytes, sr: int, ch: int, ms: int) -> bytes:
    """Dodaje ciszę na końcu strumienia PCM."""
    frames = int(sr * ms / 1000) * ch
    if frames > 0:
        pcm += b"\x00\x00" * frames  # Zakładamy 16-bit (2 bajty)
    return pcm


def _maybe_gain(pcm: bytes, gain: float) -> bytes:
    """Stosuje wzmocnienie (gain) do PCM."""
    if math.isclose(gain, 1.0, rel_tol=0.0, abs_tol=1e-9):
        return pcm
    g = max(0.1, min(gain, 3.0))
    try:
        return audioop.mul(pcm, 2, g)  # Zakładamy 16-bit (2 bajty)
    except audioop.error:
        return pcm
