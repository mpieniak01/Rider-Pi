#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/ui/face.py — „twarz” robota: LCD (SPI) lub Tkinter.

Co nowego (ta wersja):
 - takeover SPI domyślnie tylko przez fuser (zabija TYLKO PIDs trzymające /dev/spidev*),
   bez szerokiego pkill; bezpiecznie omija bieżący proces.
 - opcjonalny pkill można włączyć ENV (patrz niżej).
 - hotfix Init() w xgoscreen (brak _pwm), auto-reinit LCD po błędach,
 - ograniczenie prędkości SPI (ENV),
 - PID-lock z FORCE/override.

Subskrybuje (ZeroMQ):
  - ui.state: {"state": "idle|wake|record|process|speak|low_battery"}
  - assistant.speech: {"event": "start|end", "text": "..."}
  - audio.transcript: {"text":"...", "lang":"pl"}

ENV:
  FACE_BACKEND=auto|lcd|tk
  FACE_FPS=30
  FACE_LCD_DO_INIT=0|1        (domyślnie 1)
  FACE_LCD_ROTATE=0|180
  FACE_LCD_SPI_HZ=            (np. 12000000)

  # takeover (domyślnie fuser):
  FACE_LCD_TAKEOVER_MODE=fuser|pkill|both|off   (domyślnie: fuser)
  FACE_LCD_KILL_RE=remix\\.py|mian\\.py|main\\.py|demo.*\\.py|app_.*\\.py  (używane tylko gdy tryb pkill/both)

  # lock override:
  FACE_LOCK_OVERRIDE=0|1
"""

import os, sys, time, math, random, threading, queue, platform, atexit, signal, subprocess

# --- ścieżki projektu / bus ---------------------------------------------------
PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)
from common.bus import BusSub  # type: ignore

# --- konfiguracja -------------------------------------------------------------
BACKEND_ENV  = os.environ.get("FACE_BACKEND", "auto").lower()
FPS          = int(os.environ.get("FACE_FPS", "30"))
LCD_DO_INIT  = bool(int(os.environ.get("FACE_LCD_DO_INIT", "1")))
LCD_ROTATE   = int(os.environ.get("FACE_LCD_ROTATE", "0"))
_SPI_ENV     = os.environ.get("FACE_LCD_SPI_HZ", "").strip()
LCD_SPI_HZ   = None if not _SPI_ENV else max(1_000_000, int(_SPI_ENV))  # >=1MHz

# takeover
LCD_TAKEOVER_MODE = os.environ.get("FACE_LCD_TAKEOVER_MODE", "fuser").lower().strip()
LCD_KILL_RE       = os.environ.get("FACE_LCD_KILL_RE", r"remix\.py|mian\.py|main\.py|demo.*\.py|app_.*\.py")

# lock
LOCK_PATH     = "/tmp/rider_face.lcd.lock"
LOCK_OVERRIDE = int(os.environ.get("FACE_LOCK_OVERRIDE", "0")) != 0

COLORS = {
    "idle":        (30, 58, 138),
    "wake":        (245, 158, 11),
    "record":      (249, 115, 22),
    "process":     (124, 58, 237),
    "speak":       (16, 185, 129),
    "low_battery": (239, 68, 68),
}

# --- HOTFIX: xgoscreen.LCD_2inch.Init bez _pwm --------------------------------
def _patch_xgoscreen_pwm():
    try:
        import xgoscreen.LCD_2inch as LCD_2inch
    except Exception:
        return
    try:
        orig_Init = LCD_2inch.LCD_2inch.Init
    except Exception:
        return
    def safe_Init(self, *a, **k):
        try:
            return orig_Init(self, *a, **k)
        except AttributeError as e:
            if "_pwm" in str(e):
                class _DummyPWM:
                    def start(self,*_a,**_k): pass
                    def ChangeDutyCycle(self,*_a,**_k): pass
                    def stop(self,*_a,**_k): pass
                self._pwm = _DummyPWM()
                return orig_Init(self, *a, **k)
            raise
    LCD_2inch.LCD_2inch.Init = safe_Init
_patch_xgoscreen_pwm()

# --- PID-lock (singleton) z auto-cleanup --------------------------------------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().decode("utf-8", "ignore").replace("\x00", " ")
    except Exception:
        return ""

def acquire_lock():
    # ręczne wymuszenie: usuń lock i jedziemy
    if LOCK_OVERRIDE:
        try: os.unlink(LOCK_PATH)
        except Exception: pass

    old_pid = None
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH, "r") as f:
                old_pid = int((f.read().strip() or "0"))
        except Exception:
            old_pid = None

    if old_pid:
        alive = _pid_alive(old_pid)
        same  = "apps/ui/face.py" in _cmdline(old_pid)
        if not alive or not same:
            # lock-sierota
            try: os.unlink(LOCK_PATH)
            except Exception: pass
        else:
            # jest żywa poprzednia twarz → łagodnie zakończ tamtą
            try:
                os.kill(old_pid, signal.SIGTERM)
                for _ in range(40):  # do 2s
                    if not _pid_alive(old_pid):
                        break
                    time.sleep(0.05)
            except Exception:
                pass
            if _pid_alive(old_pid):
                print(f"[face] stara instancja (PID {old_pid}) wciąż żyje — kończę.", flush=True)
                sys.exit(0)

    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))

def release_lock():
    try: os.unlink(LOCK_PATH)
    except Exception: pass

# --- takeover helpers ----------------------------------------------------------
def _kill_pids(pids, label):
    """Łagodnie SIGTERM, po chwili SIGKILL; omija bieżący i rodzica."""
    me = os.getpid()
    ppid = os.getppid()
    left = []
    for pid in sorted(set(int(p) for p in pids if str(p).isdigit())):
        if pid in (0, 1, me, ppid):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            left.append(pid)
        except Exception:
            pass
    t0 = time.time()
    while time.time() - t0 < 1.0:
        left = [pid for pid in left if _pid_alive(pid)]
        if not left: break
        time.sleep(0.05)
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    if pids:
        print(f"[face] takeover({label}): killed {len(pids)} PID(s).", flush=True)

def _takeover_fuser():
    try:
        out = subprocess.check_output(
            ["bash","-lc","sudo fuser -v /dev/spidev0.0 /dev/spidev0.1 2>/dev/null | awk 'NF>=2 && $2 ~ /^[0-9]+$/ {print $2}' | sort -u"],
            text=True
        )
        pids = [int(x) for x in out.strip().splitlines() if x.strip().isdigit()]
        if pids:
            _kill_pids(pids, "fuser")
            time.sleep(0.2)
        else:
            print("[face] takeover(fuser): nic nie trzyma SPI.", flush=True)
    except subprocess.CalledProcessError:
        print("[face] takeover(fuser): brak fuser lub brak PIDs.", flush=True)
    except Exception as e:
        print(f"[face] takeover(fuser) warn: {e}", flush=True)

def _takeover_pkill():
    try:
        # zabij tylko znane procesy producenta (regex konfigurowalny)
        subprocess.run(["sudo","pkill","-f", LCD_KILL_RE],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[face] takeover(pkill): regex wysłany.", flush=True)
        time.sleep(0.2)
    except Exception as e:
        print(f"[face] takeover(pkill) warn: {e}", flush=True)

def _do_takeover():
    mode = LCD_TAKEOVER_MODE
    if mode == "off":
        print("[face] takeover=OFF", flush=True); return
    if mode in ("fuser","both"):
        _takeover_fuser()
    if mode in ("pkill","both"):
        _takeover_pkill()

# --- model stanu --------------------------------------------------------------
class FaceModel:
    def __init__(self):
        self.state = "idle"
        self.user_text = ""
        self.assistant_text = ""
        self.assist_speaking = False
        self.last_blink = time.time()
        self.next_blink_after = random.uniform(4.0, 9.0)
        self.speak_phase = 0.0
    def tick(self, dt: float):
        now = time.time()
        if now - self.last_blink > self.next_blink_after:
            self.last_blink = now
            self.next_blink_after = random.uniform(4.0, 9.0)
        if self.assist_speaking or self.state == "speak":
            self.speak_phase += dt * 10.0
        else:
            self.speak_phase *= 0.9
    def is_blinking(self) -> bool:
        return (time.time() - self.last_blink) < 0.14

# --- interfejs renderera ------------------------------------------------------
class BaseRenderer:
    def render(self, model: FaceModel): ...
    def close(self): ...

# --- LCD renderer -------------------------------------------------------------
class LCDRenderer(BaseRenderer):
    def __init__(self):
        # takeover TYLKO na SPI–holders
        _do_takeover()

        from PIL import Image, ImageDraw  # type: ignore
        import xgoscreen.LCD_2inch as LCD_2inch  # type: ignore
        self.Image, self.ImageDraw = Image, ImageDraw
        self.LCD_2inch = LCD_2inch

        # Inicjalizacja LCD
        self.display = LCD_2inch.LCD_2inch()
        if LCD_DO_INIT:
            try:
                self.display.Init()
                print("[face] LCD: Init()", flush=True)
            except Exception as e:
                print(f"[face] LCD: Init() fail: {e}", flush=True)

        # Opcjonalny tuning prędkości SPI
        if LCD_SPI_HZ is not None:
            try:
                spi = getattr(self.display, "SPI", None) or getattr(self.display, "spi", None)
                if spi and hasattr(spi, "max_speed_hz"):
                    spi.max_speed_hz = LCD_SPI_HZ
                    print(f"[face] LCD: spi.max_speed_hz={LCD_SPI_HZ}", flush=True)
            except Exception as e:
                print(f"[face] LCD: SPI speed set fail: {e}", flush=True)

        try:
            self.display.clear()
        except Exception:
            pass

        self.W, self.H = self.display.height, self.display.width  # zwykle 320x240
        self.splash = self.Image.new("RGB", (self.W, self.H), (0, 0, 0))
        self.draw = self.ImageDraw.Draw(self.splash)

        # szybki test: kolorowa ramka (niebieskie tło)
        self.draw.rectangle([(0,0),(self.W,self.H)], fill=(0,120,255))
        self.draw.rectangle([(6,6),(self.W-6,self.H-6)], outline=(255,255,255), width=4)
        self._err_count = 0
        self._last_reinit = 0.0
        self._safe_show(self.splash, first=True)

    def _safe_show(self, img, first=False):
        try:
            if LCD_ROTATE == 180:
                img = img.transpose(self.Image.ROTATE_180)
            self.display.ShowImage(img)
            self._err_count = 0
            return True
        except Exception as e:
            self._err_count += 1
            print(f"[face] LCD: ShowImage error ({self._err_count}): {e}", flush=True)
            # spróbuj miękkiego re-init po 2 błędach
            if self._err_count >= 2 and (time.time() - self._last_reinit) > 0.5:
                self._reinit()
            return False

    def _reinit(self):
        self._last_reinit = time.time()
        try:
            if hasattr(self.display, "module_exit"):
                try: self.display.module_exit()
                except Exception: pass
            self.display = self.LCD_2inch.LCD_2inch()
            try:
                self.display.Init()
            except Exception: pass
            try:
                self.display.clear()
            except Exception: pass
            if LCD_SPI_HZ is not None:
                spi = getattr(self.display, "SPI", None) or getattr(self.display, "spi", None)
                if spi and hasattr(spi, "max_speed_hz"):
                    spi.max_speed_hz = LCD_SPI_HZ
            print("[face] LCD: reinit done", flush=True)
            self._err_count = 0
        except Exception as e:
            print(f"[face] LCD: reinit failed: {e}", flush=True)

    def _face_geom(self):
        cx, cy = self.W // 2, self.H // 2
        eye_dx = int(self.W * 0.22)
        eye_w  = int(self.W * 0.28)
        eye_h  = int(self.H * 0.12)
        mouth_w = int(self.W * 0.68)
        mouth_y = int(self.H * 0.72)
        return cx, cy, eye_dx, eye_w, eye_h, mouth_w, mouth_y

    def render(self, model: FaceModel):
        bg = COLORS.get(model.state, COLORS["idle"])
        self.draw.rectangle([(0, 0), (self.W, self.H)], fill=bg)

        cx, cy, eye_dx, eye_w, eye_h, mouth_w, mouth_y = self._face_geom()
        blink_mul = 0.25 if model.is_blinking() or model.state == "process" else 1.0

        def oval(x1, y1, x2, y2, fill):
            self.draw.ellipse([(x1, y1), (x2, y2)], fill=fill)
        l = (cx - eye_dx - eye_w // 2, cy - int(eye_h * blink_mul),
             cx - eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
        r = (cx + eye_dx - eye_w // 2, cy - int(eye_h * blink_mul),
             cx + eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
        oval(*l, fill=(255, 255, 255)); oval(*r, fill=(255, 255, 255))

        def pupil_rect(rect, off):
            x1, y1, x2, y2 = rect
            ex, ey = (x1+x2)//2, (y1+y2)//2
            pw = int(eye_w * 0.18); ph = int(eye_h * 0.6 * blink_mul + 2)
            return (ex - pw//2 + off, ey - ph//2, ex + pw//2 + off, ey + ph//2)
        t = time.time()
        off = int(math.sin(t * (1.2 if model.state in ("wake","record","process") else 2.0)) * (eye_w * 0.06))
        self.draw.ellipse(pupil_rect(l, -off), fill=(0,0,0))
        self.draw.ellipse(pupil_rect(r, +off), fill=(0,0,0))

        amp = 0
        if model.assist_speaking or model.state == "speak":
            amp = int((math.sin(model.speak_phase) + math.sin(model.speak_phase*1.7)*0.6) * (self.H * 0.03))
        mouth_h = max(6, int(self.H * 0.04) + amp)
        self.draw.rectangle([(cx - mouth_w//2, mouth_y - mouth_h//2),
                             (cx + mouth_w//2, mouth_y + mouth_h//2)], fill=(0,0,0))

        self._safe_show(self.splash)

    def close(self):
        try:
            if hasattr(self.display, "module_exit"):
                self.display.module_exit()
        except Exception:
            pass

# --- TK renderer --------------------------------------------------------------
class TKRenderer(BaseRenderer):
    def __init__(self):
        import tkinter as tk  # type: ignore
        self.tk = tk; self.root = tk.Tk()
        self.root.title("Rider-Pi Face")
        self.W, self.H = 640, 400
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.bg = self.canvas.create_rectangle(0,0,self.W,self.H, fill="#000000", outline="")
        self.eye_l = self.canvas.create_oval(0,0,0,0, fill="white", outline="")
        self.eye_r = self.canvas.create_oval(0,0,0,0, fill="white", outline="")
        self.pupil_l = self.canvas.create_oval(0,0,0,0, fill="black", outline="")
        self.pupil_r = self.canvas.create_oval(0,0,0,0, fill="black", outline="")
        self.mouth = self.canvas.create_rectangle(0,0,0,0, fill="black", outline="")
    def render(self, model: FaceModel):
        base = COLORS.get(model.state, COLORS["idle"])
        self.canvas.itemconfig(self.bg, fill="#%02x%02x%02x" % base)
        cx, cy = self.W/2, self.H/2
        eye_dx, eye_w, eye_h = 80, 90, 60
        blink = 0.25 if model.is_blinking() or model.state=="process" else 1.0
        l = (cx-eye_dx-eye_w/2, cy-eye_h*blink, cx-eye_dx+eye_w/2, cy+eye_h*blink)
        r = (cx+eye_dx-eye_w/2, cy-eye_h*blink, cx+eye_dx+eye_w/2, cy+eye_h*blink)
        self.canvas.coords(self.eye_l, *l); self.canvas.coords(self.eye_r, *r)
        t = time.time(); off = math.sin(t*(1.2 if model.state in ("wake","record","process") else 2.0))*8
        def pup(rect, xoff):
            x1,y1,x2,y2 = rect; ex=(x1+x2)/2+xoff; ey=(y1+y2)/2; pw=22; ph=22
            return (ex-pw/2, ey-ph/2, ex+pw/2, ey+ph/2)
        self.canvas.coords(self.pupil_l, *pup(l,-off)); self.canvas.coords(self.pupil_r, *pup(r,+off))
        amp = (math.sin(model.speak_phase)+math.sin(model.speak_phase*1.7)*0.6)*12 if (model.assist_speaking or model.state=="speak") else 0
        mouth_w = 220; mouth_h = max(8, 16+amp); y = cy+90
        self.canvas.coords(self.mouth, cx-mouth_w/2, y-mouth_h/2, cx+mouth_w/2, y+mouth_h/2)
        self.root.update_idletasks(); self.root.update()
    def close(self):
        try: self.root.destroy()
        except Exception: pass

# --- wybór backendu -----------------------------------------------------------
class _Dummy(BaseRenderer):
    def render(self, model: FaceModel): pass
    def close(self): pass

def pick_renderer() -> BaseRenderer:
    if BACKEND_ENV == "lcd":
        try:
            print("[face] backend=LCD", flush=True)
            return LCDRenderer()
        except Exception as e:
            print(f"[face] LCD fail: {e} → TK", flush=True)
            try: return TKRenderer()
            except Exception: return _Dummy()
    if BACKEND_ENV == "tk":
        try: return TKRenderer()
        except Exception: return _Dummy()
    try:
        print("[face] backend=LCD(auto)", flush=True)
        return LCDRenderer()
    except Exception:
        print("[face] backend=TK(auto)", flush=True)
        try: return TKRenderer()
        except Exception: return _Dummy()

# --- app + sprzątanie ---------------------------------------------------------
def _cleanup(renderer):
    try: renderer.close()
    except Exception: pass
    release_lock()

class FaceApp:
    def __init__(self):
        acquire_lock()
        self.model = FaceModel()
        self.renderer = pick_renderer()
        self.q = queue.Queue()
        self.bus_th = threading.Thread(target=self._bus_loop, daemon=True); self.bus_th.start()
        try:
            u = platform.uname(); print(f"[face] {u.system} {u.release} {u.machine}", flush=True)
        except Exception: pass
        atexit.register(lambda: _cleanup(self.renderer))
        signal.signal(signal.SIGINT,  lambda *_: sys.exit(0))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    def _bus_loop(self):
        sub_state = BusSub("ui.state"); sub_asst = BusSub("assistant.speech"); sub_tr = BusSub("audio.transcript")
        while True:
            for sub, typ in ((sub_state,"state"), (sub_asst,"assistant"), (sub_tr,"transcript")):
                topic, payload = sub.recv(timeout_ms=50)
                if not topic or not payload: continue
                try:
                    if typ=="state":
                        self.q.put({"type":"state","state": str(payload.get("state","idle"))})
                    elif typ=="assistant":
                        self.q.put({"type":"assistant","event": str(payload.get("event","")), "text": str(payload.get("text",""))})
                    elif typ=="transcript":
                        self.q.put({"type":"transcript","text": str(payload.get("text",""))})
                except Exception: continue

    def _drain(self):
        try:
            while True:
                ev = self.q.get_nowait()
                t = ev.get("type")
                if t=="state":
                    self.model.state = ev.get("state","idle")
                elif t=="assistant":
                    evt = ev.get("event",""); txt = ev.get("text","")
                    if evt=="start":
                        self.model.assist_speaking=True; self.model.assistant_text=txt; self.model.state="speak"
                    elif evt=="end":
                        self.model.assist_speaking=False; self.model.state="idle"
                elif t=="transcript":
                    self.model.user_text = ev.get("text","")
        except queue.Empty:
            pass

    def run(self):
        dt = 1.0/max(1,FPS)
        try:
            while True:
                t0 = time.time()
                self._drain()
                self.model.tick(dt)
                self.renderer.render(self.model)
                sl = dt - (time.time()-t0)
                if sl>0: time.sleep(sl)
        except SystemExit:
            pass
        finally:
            _cleanup(self.renderer)

if __name__ == "__main__":
    FaceApp().run()
