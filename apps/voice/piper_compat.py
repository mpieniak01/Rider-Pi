import io
import wave

from piper.voice import PiperVoice


def load_voice(model_path: str):
    """Ładuje głos przez PiperVoice.load(model, model.json) i poprawia sample_rate, jeśli brak."""
    cfg = model_path + ".json"
    v = PiperVoice.load(model_path, cfg)
    # część paczek PL ma w JSON-ie sample_rate=null -> ustaw bezpieczne 22050
    if getattr(getattr(v, "config", None), "sample_rate", None) in (None, 0):
        v.config.sample_rate = 22050
    return v


def synthesize_wav_bytes(voice, text: str, length_scale=1.0, noise_scale=0.667, noise_w=0.8, sentence_silence=0.6):
    """Zwraca (wav_bytes, sample_rate). Zapis przez wave.open(...,'wb')."""
    sr = getattr(getattr(voice, "config", None), "sample_rate", None) or 22050
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit PCM
        w.setframerate(sr)
        voice.synthesize(
            text,
            w,
            length_scale=length_scale,
            noise_scale=noise_scale,
            noise_w=noise_w,
            sentence_silence=sentence_silence,
        )
    return buf.getvalue(), sr
