#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# apps/voice/main.py — voice-service na lokalnym busie (ZeroMQ)
# Funkcje:
#  - nasłuch hotwordu (Nyumaya premium) + VAD nagrywania
#  - ASR (Whisper-1), publikacja "audio.transcript"
#  - tryb standalone (domyślnie): Chat (gpt-4o-mini) + TTS (stream/mp3->mpg123)
#  - subskrypcja "tts.speak": mów dowolny tekst wysłany po busie
#
# ENV:
#   OPENAI_API_KEY       (z ~/.bash_profile ładowany automatycznie jeśli brak)
#   VOICE_STANDALONE=1   (domyślnie 1; ustaw 0 gdy podłączysz NLU/motion)
#   ALSA_DEVICE=plughw:1,0
#   HOTWORD_THRESHOLD=0.60  EXTRACTOR_GAIN=1.0
#   VAD_MODE=3 VAD_FRAME_MS=20 VAD_SILENCE_TAIL_MS=300 VAD_MAX_LEN_S=4.0
#   ENERGY_CUTOFF_DBFS=-36.0 ENERGY_TAIL_MS=180
#   STREAM_TTS=1 STREAM_CHUNK=8192  # TTS strumieniowe (mp3->mpg123)
#   RECORDINGS_DIR=/home/pi/robot/data/recordings
#   KEEP_INPUT_WAV=0 KEEP_OUTPUT_WAV=0
#   DING_PLAY_MS=200  # czas trwania krótkiego "ding" (ucięcie po ms)
#
# Bus topics:
#   PUB: "audio.transcript"   payload: {"text": "...", "lang": "pl", "ts": ..., "source":"voice"}
#   SUB: "tts.speak"          payload: {"text": "..."}

import os, sys, time, wave, shutil, threading, subprocess, platform, glob, math, tempfile, signal, json
from typing import Tuple
import numpy as np




# ── dopnij root projektu do sys.path ──────────────────────────────────────────
PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

# ── MARKER & stdout line-buffered ─────────────────────────────────────────────
print(">>> MARKER: voice-service (hotword + VAD + ASR + optional Chat/TTS) <<<", flush=True)
try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

# ── Bezpieczne logowanie ──────────────────────────────────────────────────────
def log(msg: str) -> None:
    repl = {"→":"->","←":"<-","↔":"<->","—":"-","–":"-","…":"...","“":'"',"”":'"',"’":"'"}
    try: s = str(msg)
    except Exception: s = repr(msg)
    s = s.translate(str.maketrans(repl))
    try:
        print(time.strftime("[%H:%M:%S]"), s, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((time.strftime("[%H:%M:%S] ")+s+"\n").encode("utf-8","ignore"))
        sys.stdout.flush()

# ── Info systemu ──────────────────────────────────────────────────────────────
try:
    u = platform.uname()
    print(f"System:{u.system}", flush=True)
    print(f"Release:{u.release}", flush=True)
    print(f"Machine:{u.machine}", flush=True)
    print(f"Uname:{u}", flush=True)
except Exception:
    pass

# ── Ścieżki i importy vendora ────────────────────────────────────────────────
DEMOS_ROOT = "/home/pi/RaspberryPi-CM4-main/demos"
sys.path.append(DEMOS_ROOT)

try:
    from auto_platform import AudiostreamSource, play_command, default_libpath
except Exception as e:
    log(f"BLAD: auto_platform import: {e}"); sys.exit(1)
try:
    from libnyumaya import AudioRecognition, FeatureExtractor
except Exception as e:
    log(f"BLAD: libnyumaya import: {e}"); sys.exit(1)
try:
    from xgolib import XGO
except Exception as e:
    log(f"UWAGA: xgolib niedostepny: {e}"); XGO = None
try:
    from openai import OpenAI
except Exception as e:
    log(f"BLAD: openai import: {e}"); sys.exit(1)

# bus (ZeroMQ)
from common.bus import BusPub, BusSub, now_ts

# psutil (opcjonalnie)
try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

# VAD
HAS_VAD = True
try:
    import webrtcvad
except Exception:
    HAS_VAD = False

# ── Łagodne zamykanie ─────────────────────────────────────────────────────────
_shutdown_evt = threading.Event()
def _sig_handler(signum, frame):
    log(f"Odebrano sygnal {signum} — koncze lagodnie."); _shutdown_evt.set()
signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)

# ── OPENAI KEY z ENV lub ~/.bash_profile ─────────────────────────────────────
def _load_openai_key_from_bash_profile() -> str:
    path = os.path.expanduser("~/.bash_profile")
    if not os.path.exists(path): return None
    try:
        cmd = 'source ~/.bash_profile >/dev/null 2>&1; printf "%s" "$OPENAI_API_KEY"'
        out = subprocess.run(["bash","-lc",cmd], capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            k = (out.stdout or "").strip()
            return k or None
    except Exception:
        pass
    return None

def _get_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key: return key
    key = _load_openai_key_from_bash_profile()
    if key:
        os.environ["OPENAI_API_KEY"] = key
        return key
    return None

# ── Konfig ───────────────────────────────────────────────────────────────────
def _env_float(name: str, default: float) -> float:
    try:
        v = os.environ.get(name,""); return float(v) if v else default
    except Exception:
        return default
def _env_int(name: str, default: int) -> int:
    try:
        v = os.environ.get(name,""); return int(v) if v else default
    except Exception:
        return default
def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name,"")
    if v == "": return default
    try: return bool(int(v))
    except Exception: return default

VOICE_STANDALONE = _env_bool("VOICE_STANDALONE", True)

SELF_STABILIZE = _env_int("SELF_STABILIZE", 0)  # domyślnie WYŁ.


ALSA_DEVICE     = os.environ.get("ALSA_DEVICE","plughw:1,0")
OPENAI_API_KEY  = _get_openai_api_key()

ALSA_BUFFER_US     = _env_int("ALSA_BUFFER_US", 50000)
ALSA_PERIOD_US     = _env_int("ALSA_PERIOD_US", 12000)
APLAY_FORCE_FORMAT = _env_bool("APLAY_FORCE_FORMAT", False)

REC_SAMPLERATE  = 16000
REC_CHANNELS    = 1
REC_SAMPWIDTH   = 2
REC_DURATION_S  = 5.0

RECORDINGS_DIR  = os.environ.get("RECORDINGS_DIR","/home/pi/robot/data/recordings")
KEEP_INPUT_WAV  = os.environ.get("KEEP_INPUT_WAV")  == "1"
KEEP_OUTPUT_WAV = os.environ.get("KEEP_OUTPUT_WAV") == "1"

LED_LISTEN   = [0,0,60]
LED_WAKE     = [255,180,0]
LED_RECORD   = [255,120,0]
LED_PROCESS  = [180,0,120]
LED_SPEAK    = [0,180,0]
LED_OFF      = [0,0,0]

HOTWORD_THRESHOLD = _env_float("HOTWORD_THRESHOLD", 0.60)
EXTRACTOR_GAIN    = _env_float("EXTRACTOR_GAIN", 1.0)

VAD_MODE            = _env_int("VAD_MODE", 3)
VAD_FRAME_MS        = _env_int("VAD_FRAME_MS", 20)
VAD_SILENCE_TAIL_MS = _env_int("VAD_SILENCE_TAIL_MS", 300)
VAD_MAX_LEN_S       = _env_float("VAD_MAX_LEN_S", 4.0)
ENERGY_CUTOFF_DBFS  = _env_float("ENERGY_CUTOFF_DBFS", -36.0)
ENERGY_TAIL_MS      = _env_int("ENERGY_TAIL_MS", 180)

STREAM_TTS        = _env_bool("STREAM_TTS", True)
STREAM_CHUNK      = _env_int("STREAM_CHUNK", 8192)
STREAM_PITCH      = _env_float("STREAM_PITCH", 0.0)
STREAM_TEE_OUTPUT = _env_bool("STREAM_TEE_OUTPUT", False)

BAT_WARN_PCT      = _env_int("BAT_WARN_PCT", 20)

PREMIUM_LIB = os.environ.get("HOTWORD_LIB_PATH")
if PREMIUM_LIB and not os.path.exists(PREMIUM_LIB): PREMIUM_LIB = None
if not PREMIUM_LIB:
    from auto_platform import default_libpath as _deflib
    PREMIUM_LIB = _deflib if isinstance(_deflib,str) and os.path.exists(_deflib) else None
if not PREMIUM_LIB:
    cand = os.path.join(DEMOS_ROOT,"libnyumaya_premium.so.3.1.0")
    if os.path.exists(cand): PREMIUM_LIB = cand

PREMIUM_MODEL = os.environ.get("HOTWORD_MODEL_PATH")
if PREMIUM_MODEL and not os.path.exists(PREMIUM_MODEL): PREMIUM_MODEL = None
if not PREMIUM_MODEL:
    import glob as _glob
    cands = sorted(_glob.glob(os.path.join(DEMOS_ROOT,"src","*.premium")))
    if cands: PREMIUM_MODEL = cands[0]

DING_WAV = os.path.join(DEMOS_ROOT,"src","ding.wav")
ASSETS_DING = "/home/pi/robot/assets/ding.wav"
if os.path.exists(ASSETS_DING): DING_WAV = ASSETS_DING

# ── Globals ───────────────────────────────────────────────────────────────────
client = None
g_car  = None

def _led(color):
    global g_car
    if g_car:
        try:
            g_car.rider_led(1, color); g_car.rider_led(0, color)
        except Exception:
            pass

def _ensure_recordings_dir():
    try: os.makedirs(RECORDINGS_DIR, exist_ok=True)
    except Exception as e: log(f"UWAGA: nie moge utworzyc {RECORDINGS_DIR}: {e}")

def _ts_name(prefix: str, ext=".wav") -> str:
    ts = time.strftime("%Y%m%d_%H%M%S"); ms = int((time.time()%1)*1000)
    return f"{prefix}_{ts}_{ms:03d}{ext}"

def _copy_to_recordings(src_path: str, prefix: str) -> str:
    _ensure_recordings_dir()
    dst = os.path.join(RECORDINGS_DIR, _ts_name(prefix, ".wav"))
    shutil.copy2(src_path, dst); log(f"Zapisano kopie: {dst}"); return dst

def _has_ffmpeg() -> bool: return shutil.which("ffmpeg") is not None
def _has_mpg123() -> bool: return shutil.which("mpg123") is not None

# ── Bus: pub/sub ──────────────────────────────────────────────────────────────
PUB = BusPub()             # bez prefixu; będziemy podawać pełne tematy
SUB_TTS = BusSub("tts.speak")

# ── OpenAI init ───────────────────────────────────────────────────────────────
def init_openai() -> None:
    global client
    if not OPENAI_API_KEY:
        log("BLAD: brak klucza OpenAI (ENV lub ~/.bash_profile)."); sys.exit(1)
    client = OpenAI(api_key=OPENAI_API_KEY); log("OpenAI OK.")

# ── CPU/MEM (opcjonalnie psutil) ─────────────────────────────────────────────
def _mem_used_percent_fallback() -> float:
    try:
        total = avail = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"): total = int(line.split()[1])
                elif line.startswith("MemAvailable:"): avail = int(line.split()[1])
                if total and avail: break
        if total and avail and total > 0:
            return 100.0 * (total - avail) / total
    except Exception: pass
    return 0.0

def _cpu_usage_percent_fallback() -> float:
    try:
        cores = os.cpu_count() or 1
        load1 = os.getloadavg()[0]
        return max(0.0, min(100.0, 100.0 * load1 / cores))
    except Exception: return 0.0

# ── dBFS z ramki S16LE ────────────────────────────────────────────────────────
def _dbfs_from_frame(frame_bytes: bytes) -> float:
    if not frame_bytes: return -120.0
    samples = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32)/32768.0
    if samples.size == 0: return -120.0
    rms = float(np.sqrt(np.mean(samples*samples))+1e-12)
    dbfs = 20.0*math.log10(rms); return dbfs if dbfs>-120.0 else -120.0

# ── Bateria (na starcie) ─────────────────────────────────────────────────────
def _read_battery_from_xgo():
    if not g_car: return None
    for name in ("rider_read_battery","battery","get_battery","getVoltage","get_voltage"):
        try:
            if hasattr(g_car, name):
                fn = getattr(g_car, name)
                v = fn() if callable(fn) else fn
                if isinstance(v,(int,float)) and 0<=v<=100: return int(round(v))
        except Exception: continue
    return None

def battery_diag():
    pct = _read_battery_from_xgo()
    if pct is None: log("Bateria: nie udalo sie odczytac.")
    else:
        log(f"Bateria: {pct}%"); print(f"vol:{pct}%", flush=True)
        if pct <= BAT_WARN_PCT: log(f"UWAGA: niski poziom baterii ({pct}%).")

# ── Nagrywanie: VAD ──────────────────────────────────────────────────────────
def nagraj_glos() -> str:
    return _nagraj_vad() if HAS_VAD else _nagraj_fixed()

def _nagraj_fixed() -> str:
    log("Nagrywanie (fixed 5 s)..."); _led(LED_RECORD)
    stream = AudiostreamSource(); stream.start()
    frames=[]; start=time.time(); bpf=REC_CHANNELS*REC_SAMPWIDTH; chunk=1024*bpf
    while time.time()-start < REC_DURATION_S and not _shutdown_evt.is_set():
        data = stream.read(chunk, chunk)
        if data: frames.append(data)
        else: time.sleep(0.003)
    stream.stop(); del stream; time.sleep(0.01)
    path = os.path.join(tempfile.gettempdir(), f"ask_{int(time.time()*1000)}.wav")
    with wave.open(path,'wb') as wf:
        wf.setnchannels(REC_CHANNELS); wf.setsampwidth(REC_SAMPWIDTH); wf.setframerate(REC_SAMPLERATE)
        wf.writeframes(b"".join(frames))
    return path

def _nagraj_vad() -> str:
    log("Nagrywanie (VAD, szybki tail)..."); _led(LED_RECORD)
    vad = webrtcvad.Vad(int(VAD_MODE))
    stream = AudiostreamSource(); stream.start()
    frame_ms = VAD_FRAME_MS if VAD_FRAME_MS in (10,20,30) else 20
    samples_per_frame = int(REC_SAMPLERATE*(frame_ms/1000.0))
    frame_bytes = samples_per_frame*REC_CHANNELS*REC_SAMPWIDTH
    voiced = bytearray(); start_ts=time.time()
    silence_vad_ms=0; silence_energy_ms=0; started=False
    try:
        while not _shutdown_evt.is_set():
            data = stream.read(frame_bytes, frame_bytes)
            if not data: time.sleep(0.003); continue
            dbfs = _dbfs_from_frame(data)
            try: is_speech = vad.is_speech(data, REC_SAMPLERATE)
            except Exception: is_speech=False
            if is_speech:
                started=True; silence_vad_ms=0; silence_energy_ms=0; voiced.extend(data)
            else:
                if started:
                    silence_vad_ms += frame_ms
                    if dbfs <= ENERGY_CUTOFF_DBFS: silence_energy_ms += frame_ms
                    else: silence_energy_ms = 0
                    voiced.extend(data)
            if started and (silence_vad_ms>=VAD_SILENCE_TAIL_MS or silence_energy_ms>=ENERGY_TAIL_MS): break
            if time.time()-start_ts > VAD_MAX_LEN_S: break
    finally:
        stream.stop(); del stream; time.sleep(0.01)
    if not voiced: voiced.extend(b"\x00"*frame_bytes)
    path = os.path.join(tempfile.gettempdir(), f"ask_{int(time.time()*1000)}.wav")
    with wave.open(path,'wb') as wf:
        wf.setnchannels(REC_CHANNELS); wf.setsampwidth(REC_SAMPWIDTH); wf.setframerate(REC_SAMPLERATE)
        wf.writeframes(voiced)
    return path

# ── Odtwarzanie WAV (aplay) ──────────────────────────────────────────────────
def _aplay_once(path: str, buffer_us: int, period_us: int, force_fmt: bool, quiet: bool) -> Tuple[bool, str]:
    cmd = ["aplay","-D",ALSA_DEVICE]
    if quiet: cmd.insert(1,"-q")
    if force_fmt: cmd += ["-r","48000","-f","S16_LE","-c","1","-t","wav"]
    if buffer_us>0: cmd += ["--buffer-time", str(buffer_us)]
    if period_us>0: cmd += ["--period-time", str(period_us)]
    cmd += [path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        stderr = (proc.stderr or "").lower()
        xrun = ("underrun" in stderr) or ("xrun" in stderr)
        success = (proc.returncode == 0) and (not xrun)
        return success, (proc.stderr or proc.stdout or "")
    except Exception as e:
        return False, str(e)

def odtworz_dzwiek(filename: str) -> bool:
    log(f"Odtwarzam: {filename}"); _led(LED_SPEAK)
    ok, msg = _aplay_once(filename, ALSA_BUFFER_US, ALSA_PERIOD_US, False, False)
    if ok: return True
    ok, msg = _aplay_once(filename, 120000, 30000, True, False)
    if ok: return True
    ok, msg = _aplay_once(filename, 0, 0, False, True)
    if not ok: log(f"APLAY niepowodzenie: {msg.strip()}")
    return ok

# ── ASR + Chat ────────────────────────────────────────────────────────────────
def transkrybuj(audio_file: str) -> str:
    t0=time.time(); log("Transkrypcja -> OpenAI...")
    with open(audio_file,"rb") as f:
        tr = client.audio.transcriptions.create(model="whisper-1", file=f)
    t1=time.time()
    log(f"TIMING: ASR={(t1-t0):.2f}s")
    return tr.text

def chat_reply(user_text: str) -> str:
    log("Chat -> OpenAI..."); t2=time.time()
    resp = client.chat.completions.create(
        model="gpt-4o-mini", temperature=0.4,
        messages=[
            {"role":"system","content":"Jestes asystentem robota XGO. Odpowiadaj jednym krotkim zdaniem po polsku."},
            {"role":"user","content":user_text},
        ])
    ans = resp.choices[0].message.content
    t3=time.time(); log(f"TIMING: CHAT={(t3-t2):.2f}s")
    return ans

# ── TTS STREAMING (mp3 -> mpg123 stdin) ───────────────────────────────────────
def tts_stream(text: str) -> bool:
    if not STREAM_TTS or not _has_mpg123(): return False
    _led(LED_SPEAK)
    log("Synteza mowy (stream, mp3->mpg123)...")
    t0=time.time()
    cmd = ["mpg123","-q"]
    if ALSA_DEVICE: cmd += ["-a", ALSA_DEVICE]
    if abs(STREAM_PITCH) > 1e-3: cmd += ["--pitch", str(STREAM_PITCH)]
    cmd += ["-"]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    except Exception as e:
        log(f"STREAM_TTS: nie uruchomie mpg123: {e}"); return False
    try:
        with client.audio.speech.with_streaming_response.create(
            model="tts-1", voice="alloy", input=text
        ) as r:
            first=None
            for chunk in r.iter_bytes(8192):
                if not chunk: continue
                try:
                    proc.stdin.write(chunk); proc.stdin.flush()
                    if first is None:
                        first=time.time(); log(f"TIMING: TTS_TTFB={(first-t0):.2f}s")
                except Exception:
                    break
    except Exception as e:
        log(f"STREAM_TTS blad: {e}")
        try: proc.stdin.close(); proc.terminate()
        except Exception: pass
        return False
    try: proc.stdin.close()
    except Exception: pass
    try: rc = proc.wait(timeout=20)
    except Exception: rc=-1
    t1=time.time(); log(f"TIMING: TTS_STREAM={(t1-t0):.2f}s")
    return rc==0

# ── Krótki, nieblokujący "ding" po hotword ───────────────────────────────────
def _play_ding_ms(ms: int = None):
    """Krótki ‚ding’ w tle; nie blokuje wątku i nie wstrzymuje wejścia audio."""
    if not os.path.exists(DING_WAV):
        return
    ms = int(os.environ.get("DING_PLAY_MS", ms if ms is not None else 200))
    try:
        cmd = ["aplay", "-q", "-D", ALSA_DEVICE]
        if ALSA_BUFFER_US > 0: cmd += ["--buffer-time", str(ALSA_BUFFER_US)]
        if ALSA_PERIOD_US > 0: cmd += ["--period-time", str(ALSA_PERIOD_US)]
        cmd += [DING_WAV]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(max(0.05, ms/1000.0))
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=0.2)
            except Exception:
                proc.kill()
    except Exception as e:
        log(f"DING error: {e}")

# ── Wykonanie cyklu po hotword ────────────────────────────────────────────────
def on_wake():
    _led(LED_WAKE)
    wav_path=None
    try:
        t_all0=time.time()
        wav_path = nagraj_glos()
        if KEEP_INPUT_WAV and wav_path and os.path.exists(wav_path):
            try: _copy_to_recordings(wav_path,"pytanie")
            except Exception as e: log(f"Nie zapisano kopii pytania: {e}")
        _led(LED_PROCESS)
        user_text = transkrybuj(wav_path)
        log(f"Uzytkownik: {user_text}")

        # PUB: audio.transcript (zawsze)
        PUB.publish("audio.transcript", {
            "text": user_text, "lang": "pl", "ts": now_ts(), "source": "voice"
        })

        if VOICE_STANDALONE:
            ans = chat_reply(user_text)
            log(f"Asystent: {ans}")
            ok = tts_stream(ans)
            if not ok:
                pass

        t_all1=time.time(); log(f"TIMING: TOTAL={(t_all1 - t_all0):.2f}s")
    finally:
        if wav_path and os.path.exists(wav_path):
            try: os.unlink(wav_path)
            except Exception: pass
        _led(LED_LISTEN)

# ── Opcjonalne score z detektora ──────────────────────────────────────────────
def _try_get_score(detector, keyword_id):
    for attr in ("getModelScore","get_score","getLastScore","getScores"):
        try:
            fn = getattr(detector, attr, None)
            if not fn: continue
            val = fn() if attr=="getScores" else fn(keyword_id)
            if isinstance(val,(list,tuple)) and val:
                return float(val[0])
            try: return float(val)
            except Exception: continue
        except Exception:
            continue
    return None

# ── Hotword thread ────────────────────────────────────────────────────────────
def start_hotword_listener() -> Tuple[threading.Thread, threading.Event]:
    stop_flag = threading.Event()
    def worker():
        log("Hotword: watek startuje...")
        if not PREMIUM_LIB or not PREMIUM_MODEL:
            log("BLAD: brak lib .so lub modelu .premium — hotword wylaczony.")
            return
        _led(LED_LISTEN)
        audio_stream=None
        try:
            audio_stream = AudiostreamSource(); audio_stream.start()
            extractor = FeatureExtractor(PREMIUM_LIB); detector = AudioRecognition(PREMIUM_LIB)
            log(f"Hotword: laduje .premium: {os.path.basename(PREMIUM_MODEL)}")
            keyword_id = detector.addModel(PREMIUM_MODEL, HOTWORD_THRESHOLD)
            bufsize = detector.getInputDataSize(); last_stat=time.time()
            log(f"Ustawienia: ALSA_DEVICE={ALSA_DEVICE}")
            log(f"Ustawienia: HOTWORD_THRESHOLD={HOTWORD_THRESHOLD:.2f} EXTRACTOR_GAIN={EXTRACTOR_GAIN:.2f} VAD={'ON' if HAS_VAD else 'OFF'}")
            log(f"QuickTail: ENERGY_CUTOFF_DBFS={ENERGY_CUTOFF_DBFS:.1f} dBFS, ENERGY_TAIL_MS={ENERGY_TAIL_MS} ms")
            log("NASLUCH AKTYWNY. Powiedz hotword lub naciśnij ENTER w konsoli.")
            if HAS_PSUTIL:
                try: psutil.cpu_percent(None)
                except Exception: pass
            while not stop_flag.is_set() and not _shutdown_evt.is_set():
                frame = audio_stream.read(bufsize*2, bufsize*2)
                if not frame:
                    time.sleep(0.003); continue
                dbfs = _dbfs_from_frame(frame)
                features = extractor.signalToMel(frame, EXTRACTOR_GAIN)
                prediction = detector.runDetection(features)
                score = _try_get_score(detector, keyword_id)
                now=time.time()
                if now - last_stat >= 1.0:
                    if HAS_PSUTIL:
                        try:
                            cpu = psutil.cpu_percent(None)
                            mem = psutil.virtual_memory().percent
                        except Exception:
                            cpu = _cpu_usage_percent_fallback()
                            mem = _mem_used_percent_fallback()
                    else:
                        cpu = _cpu_usage_percent_fallback()
                        mem = _mem_used_percent_fallback()
                    if score is None:
                        log(f"LEVEL={dbfs:5.1f} dBFS | THR={HOTWORD_THRESHOLD:.2f} | SCORE=n/a | CPU={cpu:4.1f}% | MEM={mem:4.1f}%")
                    else:
                        log(f"LEVEL={dbfs:5.1f} dBFS | THR={HOTWORD_THRESHOLD:.2f} | SCORE={score:.2f} | CPU={cpu:4.1f}% | MEM={mem:4.1f}%")
                    last_stat = now

                if prediction != 0 and prediction == keyword_id:
                    log("HOTWORD: wykryto.")
                    # 1) zwolnij WEJŚCIE audio NAJPIERW
                    try:
                        audio_stream.stop()
                    except Exception:
                        pass
                    try:
                        del audio_stream
                    except Exception:
                        pass
                    time.sleep(0.02)

                    # 2) krótki, nieblokujący 'ding'
                    _play_ding_ms()  # domyślnie 200 ms; steruj DING_PLAY_MS

                    # 3) nagrywaj komendę NATYCHMIAST
                    on_wake()

                    if _shutdown_evt.is_set() or stop_flag.is_set():
                        break
                    audio_stream = AudiostreamSource(); audio_stream.start(); _led(LED_LISTEN)
        except Exception as e:
            log(f"BLAD watku hotword: {e}")
        finally:
            try:
                if audio_stream: audio_stream.stop()
            except Exception: pass
            _led(LED_OFF); log("Hotword: watek zakonczony.")
    th = threading.Thread(target=worker, daemon=True); th.start()
    return th, stop_flag

# ── Ręczny trigger oraz SUB tts.speak ─────────────────────────────────────────
def manual_trigger_thread(stop_flag: threading.Event) -> threading.Thread:
    def manual():
        log("Ręczny trigger: ENTER = pytanie, 'q'+ENTER = wyjście.")
        while not stop_flag.is_set() and not _shutdown_evt.is_set():
            try: line = sys.stdin.readline()
            except Exception: break
            if stop_flag.is_set() or _shutdown_evt.is_set(): break
            if line is None: continue
            s = line.strip().lower()
            if s == "q":
                _shutdown_evt.set(); stop_flag.set(); break
            if s == "":
                log("MANUAL: wyzwolenie."); on_wake()
    th = threading.Thread(target=manual, daemon=True); th.start(); return th

def tts_subscriber_thread(stop_flag: threading.Event) -> threading.Thread:
    def run():
        log("SUB: tts.speak")
        while not stop_flag.is_set() and not _shutdown_evt.is_set():
            topic, payload = SUB_TTS.recv(timeout_ms=200)
            if topic is None: continue
            try:
                text = payload.get("text","")
            except Exception:
                continue
            if text:
                tts_stream(text)
                _led(LED_LISTEN)
    th = threading.Thread(target=run, daemon=True); th.start(); return th

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log("Start voice-service")
    if XGO:
        try:
            g_car = XGO("xgorider"); log("XGO OK.")
        except Exception as e:
            log(f"UWAGA: XGO init: {e}"); g_car = None
    else:
        g_car=None

    battery_diag()
    init_openai()

    hotword_thread=None; hotword_stop=threading.Event()
    th, st = start_hotword_listener(); hotword_thread, hotword_stop = th, st
    manual_th = manual_trigger_thread(hotword_stop)
    sub_tts_th = tts_subscriber_thread(hotword_stop)

    try:
        while not _shutdown_evt.is_set():
            time.sleep(1)
    finally:
        hotword_stop.set()
        _led(LED_OFF)
        time.sleep(0.2)
        log("Bye.")
