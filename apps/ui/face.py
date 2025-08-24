#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/ui/face2.py — „twarz” robota: LCD (SPI) lub Tkinter.

UX:
 - Przewodnik proporcji (elipsa) – FACE_GUIDE=1, regulowana FACE_HEAD_KY (domyślnie 1.04)
 - Brwi wyżej (~16% S), łagodny łuk; opcjonalne okrągłe końcówki (FACE_BROW_CAPS=1)
 - Źrenice: mniejszy bias do środka (~S*0.017), asymetria fazy, krótkie sakkady po mrugnięciu
 - Uśmiech domyślny (∪); usta ~7% krótsze, nieco wyżej
 - W mowie usta „oddychają” wysokością i delikatnie szerokością
 - Mrugnięcie 90 ms + „after-blink” 40 ms
 - Benchmark na STDOUT (FACE_BENCH=1), adaptacyjny FPS (FACE_AUTO_FPS=1)
"""

import os, sys, time, math, random, threading, queue, platform, atexit, signal, subprocess
from time import perf_counter

# --- ścieżki projektu / bus ---------------------------------------------------
PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)
from common.bus import BusSub  # type: ignore

# --- konfiguracja -------------------------------------------------------------
BACKEND_ENV  = os.environ.get("FACE_BACKEND", "auto").lower()
FPS          = int(os.environ.get("FACE_FPS", "30"))
AUTO_FPS     = int(os.environ.get("FACE_AUTO_FPS", "1")) != 0
BENCH        = int(os.environ.get("FACE_BENCH", "1")) != 0
GUIDE        = int(os.environ.get("FACE_GUIDE", "1")) != 0
BROW_CAPS    = int(os.environ.get("FACE_BROW_CAPS", "0")) != 0  # okrągłe końcówki brwi (domyślnie OFF)

LCD_DO_INIT  = bool(int(os.environ.get("FACE_LCD_DO_INIT", "1")))
LCD_ROTATE   = int(os.environ.get("FACE_LCD_ROTATE", "270"))
_SPI_ENV     = os.environ.get("FACE_LCD_SPI_HZ", "").strip()
LCD_SPI_HZ   = None if not _SPI_ENV else max(1_000_000, int(_SPI_ENV))  # >=1MHz

# delikatna elipsa głowy (skala w pionie względem promienia w poziomie)
try:
    HEAD_KY = float(os.environ.get("FACE_HEAD_KY", "1.04"))
except Exception:
    HEAD_KY = 1.04
HEAD_KY = max(0.90, min(1.20, HEAD_KY))

# takeover
LCD_TAKEOVER_MODE = os.environ.get("FACE_LCD_TAKEOVER_MODE", "both").lower().strip()
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

# --- PID-lock -----------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    try: os.kill(pid, 0); return True
    except OSError: return False

def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().decode("utf-8", "ignore").replace(" ", " ")
    except Exception:
        return ""

def acquire_lock():
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
        same  = "apps/ui/face" in _cmdline(old_pid)
        if not alive or not same:
            try: os.unlink(LOCK_PATH)
            except Exception: pass
        else:
            try:
                os.kill(old_pid, signal.SIGTERM)
                for _ in range(40):
                    if not _pid_alive(old_pid): break
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
    me = os.getpid(); ppid = os.getppid(); left = []
    for pid in sorted(set(int(p) for p in pids if str(p).isdigit())):
        if pid in (0, 1, me, ppid): continue
        try: os.kill(pid, signal.SIGTERM); left.append(pid)
        except Exception: pass
    t0 = time.time()
    while time.time() - t0 < 1.0:
        left = [pid for pid in left if _pid_alive(pid)]
        if not left: break
        time.sleep(0.05)
    for pid in left:
        try: os.kill(pid, signal.SIGKILL)
        except Exception: pass
    if pids:
        print(f"[face] takeover({label}): killed {len(pids)} PID(s).", flush=True)

def _takeover_fuser():
    try:
        out = subprocess.check_output(
            ["bash","-lc","sudo fuser -v /dev/spidev0.0 /dev/spidev0.1 2>/dev/null | awk 'NF>=2 && $2 ~ /^[0-9]+$/ {print $2}' | sort -u"],
            text=True
        )
        pids = [int(x) for x in out.strip().splitlines() if x.strip().isdigit()]
        if pids: _kill_pids(pids, "fuser"); time.sleep(0.2)
        else: print("[face] takeover(fuser): nic nie trzyma SPI.", flush=True)
    except subprocess.CalledProcessError:
        print("[face] takeover(fuser): brak fuser lub brak PIDs.", flush=True)
    except Exception as e:
        print(f"[face] takeover(fuser) warn: {e}", flush=True)

def _takeover_pkill():
    try:
        subprocess.run(["sudo","pkill","-f", LCD_KILL_RE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[face] takeover(pkill): regex wysłany.", flush=True)
        time.sleep(0.2)
    except Exception as e:
        print(f"[face] takeover(pkill) warn: {e}", flush=True)

def _do_takeover():
    mode = LCD_TAKEOVER_MODE
    if mode == "off":
        print("[face] takeover=OFF", flush=True); return
    if mode in ("fuser","both"): _takeover_fuser()
    if mode in ("pkill","both"): _takeover_pkill()

# --- model stanu --------------------------------------------------------------
class FaceModel:
    def __init__(self):
        self.state = "idle"
        self.user_text = ""
        self.assistant_text = ""
        self.assist_speaking = False

        # mruganie
        self.last_blink = time.time()
        self.next_blink_after = random.uniform(5.0, 8.0)
        self.blink_close_ms = 0.090
        self.blink_after_ms = 0.040
        self._blink_triggered = False

        # mowa
        self.speak_phase = 0.0

        # sakkady (gaze offset, px)
        self.gaze_dx = 0.0

    def tick(self, dt: float):
        now = time.time()

        # blink schedule
        self._blink_triggered = False
        if now - self.last_blink > self.next_blink_after:
            self.last_blink = now
            self.next_blink_after = random.uniform(5.0, 8.0)
            self._blink_triggered = True
            # po mrugnięciu krótka sakkada
            self.gaze_dx += random.uniform(-4.0, 4.0)

        # wygaszanie sakkady
        self.gaze_dx *= 0.86

        # mowa
        if self.assist_speaking or self.state == "speak":
            self.speak_phase += dt * 10.0
        else:
            self.speak_phase *= 0.9

    def blink_mul(self) -> float:
        t = time.time() - self.last_blink
        if t < self.blink_close_ms:
            return 0.25           # zamknięte
        if t < self.blink_close_ms + self.blink_after_ms:
            return 0.6            # after-blink: półprzymknięte
        return 1.0

# --- interfejs renderera ------------------------------------------------------
class BaseRenderer:
    _bench_draw_ms: float = 0.0
    _bench_push_ms: float = 0.0
    def render(self, model: FaceModel): ...
    def close(self): ...

# --- LCD renderer -------------------------------------------------------------
class LCDRenderer(BaseRenderer):
    def __init__(self):
        _do_takeover()
        from PIL import Image, ImageDraw  # type: ignore
        import xgoscreen.LCD_2inch as LCD_2inch  # type: ignore
        self.Image, self.ImageDraw = Image, ImageDraw
        self.LCD_2inch = LCD_2inch

        self.display = LCD_2inch.LCD_2inch()
        if LCD_DO_INIT:
            try:
                self.display.Init(); print("[face] LCD: Init()", flush=True)
            except Exception as e:
                print(f"[face] LCD: Init() fail: {e}", flush=True)

        self._force_backlight_on()

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
        time.sleep(0.3)

        try:
            self.W, self.H = int(self.display.width), int(self.display.height)
        except Exception:
            self.W, self.H = 240, 320
        print(f"[face] LCD: W={self.W} H={self.H}", flush=True)
        print(f"[face] LCD: rotate={LCD_ROTATE}", flush=True)

        # Rozmiar kanwy (rysujemy PRZED rotacją)
        self.CW, self.CH = (self.W, self.H) if LCD_ROTATE in (0, 180) else (self.H, self.W)

        self.splash = self.Image.new("RGB", (self.CW, self.CH), (0, 0, 0))
        self.draw = self.ImageDraw.Draw(self.splash)
        self._err_count = 0; self._last_reinit = 0.0

        # start screen
        self.draw.rectangle([(0,0),(self.CW,self.CH)], fill=(0,120,255))
        self.draw.rectangle([(6,6),(self.CW-6,self.CH-6)], outline=(255,255,255), width=4)
        self._safe_show(self.splash, first=True)

    def _safe_show(self, img, first=False):
        t1 = perf_counter()
        try:
            if img.size != (self.CW, self.CH):
                img = img.resize((self.CW, self.CH))
            if LCD_ROTATE in (90, 270):
                img = img.transpose(self.Image.ROTATE_90 if LCD_ROTATE==90 else self.Image.ROTATE_270)
            elif LCD_ROTATE == 180:
                img = img.transpose(self.Image.ROTATE_180)
            if img.size != (self.W, self.H):
                img = img.resize((self.W, self.H))
            try:
                buf = self.display.getbuffer(img)  # type: ignore[attr-defined]
            except Exception:
                buf = img
            self.display.ShowImage(buf)
            self._err_count = 0
            self._bench_push_ms = (perf_counter() - t1) * 1000.0
            return True
        except Exception as e:
            self._err_count += 1
            print(f"[face] LCD: ShowImage error ({self._err_count}): {e}", flush=True)
            if self._err_count >= 2 and (time.time() - self._last_reinit) > 0.5:
                self._reinit()
            self._bench_push_ms = (perf_counter() - t1) * 1000.0
            return False

    def _reinit(self):
        self._last_reinit = time.time()
        try:
            if hasattr(self.display, "module_exit"):
                try: self.display.module_exit()
                except Exception: pass
            self.display = self.LCD_2inch.LCD_2inch()
            try: self.display.Init()
            except Exception: pass
            try: self.display.clear()
            except Exception: pass
            self._force_backlight_on()
            if LCD_SPI_HZ is not None:
                spi = getattr(self.display, "SPI", None) or getattr(self.display, "spi", None)
                if spi and hasattr(spi, "max_speed_hz"):
                    spi.max_speed_hz = LCD_SPI_HZ
            print("[face] LCD: reinit done", flush=True)
            self._err_count = 0
        except Exception as e:
            print(f"[face] LCD: reinit failed: {e}", flush=True)

    def _force_backlight_on(self):
        try:
            for name in ("bl_DutyCycle", "BL_DutyCycle", "SetBL", "set_bl", "set_backlight"):
                fn = getattr(self.display, name, None)
                if callable(fn):
                    try:
                        fn(100)
                        print("[face] LCD: backlight 100%", flush=True)
                        return
                    except Exception:
                        pass
            import RPi.GPIO as GPIO  # type: ignore
            pin = int(os.environ.get("FACE_LCD_BL_PIN","13"))
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, True)
            print(f"[face] LCD: BL pin {pin}=HIGH", flush=True)
        except Exception as e:
            print(f"[face] LCD: backlight set warn: {e}", flush=True)

    def _face_geom(self):
        cx, cy = self.CW // 2, self.CH // 2
        S = min(self.CW, self.CH)
        eye_dx = int(S * 0.22)
        eye_w  = int(S * 0.28)
        eye_h  = int(S * 0.12)
        mouth_w = int(S * 0.58)
        mouth_y = cy + int(S * 0.235)
        return cx, cy, eye_dx, eye_w, eye_h, mouth_w, mouth_y

    def _ellipse_point(self, x0, y0, x1, y1, ang_deg):
        cx = (x0 + x1) / 2.0; cy = (y0 + y1) / 2.0
        rx = (x1 - x0) / 2.0; ry = (y1 - y0) / 2.0
        t = math.radians(ang_deg)
        return (cx + rx * math.cos(t), cy + ry * math.sin(t))

    def render(self, model: FaceModel):
        t0 = perf_counter()
        bg = COLORS.get(model.state, COLORS["idle"])
        self.draw.rectangle([(0, 0), (self.CW, self.CH)], fill=bg)

        cx, cy, eye_dx, eye_w, eye_h, mouth_w, mouth_y = self._face_geom()
        blink_mul = model.blink_mul()
        S = min(self.CW, self.CH)

        # przewodnik — elipsa (lekko rozciągnięta w pionie HEAD_KY)
        if GUIDE:
            M = int(S * 0.04)
            rx_limit = self.CW/2 - M
            ry_limit = self.CH/2 - M
            rx = int(min(rx_limit, ry_limit / max(0.001, HEAD_KY)))
            ry = int(min(ry_limit, rx * HEAD_KY))
            self.draw.ellipse([(cx - rx, cy - ry), (cx + rx, cy + ry)],
                              outline=(220,235,255), width=2)

        # oczy (białka)
        l = (cx - eye_dx - eye_w // 2, cy - int(eye_h * blink_mul),
             cx - eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
        r = (cx + eye_dx - eye_w // 2, cy - int(eye_h * blink_mul),
             cx + eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
        self.draw.ellipse(l, fill=(255,255,255))
        self.draw.ellipse(r, fill=(255,255,255))

        # źrenice (oscylacja + sakkady + bias do środka)
        def pupil_rect(rect, off):
            x1, y1, x2, y2 = rect
            ex, ey = (x1+x2)//2, (y1+y2)//2
            pw = int(eye_w * 0.18); ph = int(eye_h * 0.6 * blink_mul + 2)
            return (ex - pw//2 + off, ey - ph//2, ex + pw//2 + off, ey + ph//2)
        t = time.time()
        freq  = 1.2 if model.state in ("wake","record","process") else 2.0
        amp   = eye_w * 0.04
        phase = 0.35
        bias  = int(S * 0.017)
        offL = int(math.sin(t * freq) * amp + model.gaze_dx)
        offR = int(math.sin(t * freq + phase) * amp + model.gaze_dx)
        self.draw.ellipse(pupil_rect(l,  +bias + offL), fill=(0,0,0))
        self.draw.ellipse(pupil_rect(r,  -bias + offR), fill=(0,0,0))

        # brwi
        brow_y = cy - int(S * 0.16)
        brow_w = int(S * 0.19)
        brow_h = int(S * 0.10)
        stroke = max(6, int(S * 0.03))
        k_brow = {"idle": 0.12, "wake": 0.08, "record": 0.06, "process": 0.02, "low_battery": 0.18}.get(model.state, 0.08)
        def draw_brow(ex: int, k: float):
            x0, y0 = ex - brow_w // 2, brow_y - brow_h
            x1, y1 = ex + brow_w // 2, brow_y + brow_h
            if k < 0: start, end = 20, 160    # ∪
            else:     start, end = 200, 340   # ∩
            self.draw.arc([(x0, y0), (x1, y1)], start=start, end=end, fill=(255,255,255), width=stroke)
            if BROW_CAPS:
                for ang in (start, end):
                    px, py = self._ellipse_point(x0, y0, x1, y1, ang)
                    self.draw.ellipse([(px - stroke/2, py - stroke/2), (px + stroke/2, py + stroke/2)], fill=(255,255,255))
        draw_brow(cx - eye_dx, k_brow); draw_brow(cx + eye_dx, k_brow)

        # usta
        def mouth_curvature_for(state: str) -> float:
            k = {"idle": -0.48, "wake": -0.36, "record": -0.28,
                 "process": -0.22, "low_battery": 0.25, "speak": -0.18}.get(state, -0.24)
            if state != "low_battery" and k >= 0:
                k = -0.18 if k == 0 else -abs(k)
            return k
        def draw_mouth_curve(cx_i: int, y: int, w: int, k: float) -> None:
            depth = max(6, int(abs(k) * S * 0.28))
            x0, y0, x1, y1 = cx_i - w // 2, y - depth, cx_i + w // 2, y + depth
            if k < 0: start, end = 20, 160   # smile (∪)
            else:     start, end = 200, 340  # frown (∩)
            self.draw.arc([(x0, y0), (x1, y1)], start=start, end=end,
                          fill=(0,0,0), width=max(8, int(S * 0.055)))
        if model.assist_speaking or model.state == "speak":
            amp_m = (math.sin(model.speak_phase) + math.sin(model.speak_phase*1.7)*0.6)
            height = max(6, int(S * 0.04) + int(amp_m * (S * 0.03)))
            width  = int(mouth_w * (1.0 + 0.06 * max(0.0, amp_m)))
            self.draw.rectangle([(cx - width//2, mouth_y - height//2),
                                 (cx + width//2, mouth_y + height//2)], fill=(0,0,0))
        else:
            draw_mouth_curve(cx, mouth_y, mouth_w, mouth_curvature_for(model.state))

        self._bench_draw_ms = (perf_counter() - t0) * 1000.0
        self._safe_show(self.splash)

    def close(self):
        try:
            if hasattr(self.display, "module_exit"): self.display.module_exit()
        except Exception:
            pass

# --- TK renderer --------------------------------------------------------------
class TKRenderer(BaseRenderer):
    def __init__(self):
        import tkinter as tk  # type: ignore
        self.tk = tk
        self.root = tk.Tk()
        self.root.title("Rider-Pi Face")
        self.W, self.H = 640, 400
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.bg = self.canvas.create_rectangle(0,0,self.W,self.H, fill="#000000", outline="")
        self.face_circle = self.canvas.create_oval(0,0,0,0, outline="#E0EBFF", width=2)
        self.eye_l = self.canvas.create_oval(0,0,0,0, fill="white", outline="")
        self.eye_r = self.canvas.create_oval(0,0,0,0, fill="white", outline="")
        self.pupil_l = self.canvas.create_oval(0,0,0,0, fill="black", outline="")
        self.pupil_r = self.canvas.create_oval(0,0,0,0, fill="black", outline="")
        self.mouth = self.canvas.create_rectangle(0,0,0,0, fill="black", outline="")
        self.brow_l = self.canvas.create_arc(0,0,0,0, start=0, extent=0, style="arc", width=8, outline="white")
        self.brow_r = self.canvas.create_arc(0,0,0,0, start=0, extent=0, style="arc", width=8, outline="white")
        self.brow_l_cap1 = self.canvas.create_oval(0,0,0,0, fill="white", outline="")
        self.brow_l_cap2 = self.canvas.create_oval(0,0,0,0, fill="white", outline="")
        self.brow_r_cap1 = self.canvas.create_oval(0,0,0,0, fill="white", outline="")
        self.brow_r_cap2 = self.canvas.create_oval(0,0,0,0, fill="white", outline="")
        self.mouth_arc = self.canvas.create_arc(0,0,0,0, start=0, extent=0, style="arc", width=10, outline="black")

    def _ellipse_point(self, x0, y0, x1, y1, ang_deg):
        cx = (x0 + x1) / 2.0; cy = (y0 + y1) / 2.0
        rx = (x1 - x0) / 2.0; ry = (y1 - y0) / 2.0
        t = math.radians(ang_deg)
        return (cx + rx * math.cos(t), cy + ry * math.sin(t))

    def render(self, model: FaceModel):
        t0 = perf_counter()
        base = COLORS.get(model.state, COLORS["idle"])
        self.canvas.itemconfig(self.bg, fill="#%02x%02x%02x" % base)

        cx, cy = self.W/2, self.H/2
        S = min(self.W, self.H)
        eye_dx, eye_w, eye_h = S*0.22, S*0.28, S*0.12
        blink = model.blink_mul()

        # przewodnik — elipsa (lekko rozciągnięta w pionie HEAD_KY)
        if GUIDE:
            M = int(S * 0.04)
            rx_limit = self.W/2 - M
            ry_limit = self.H/2 - M
            rx = min(rx_limit, ry_limit / max(0.001, HEAD_KY))
            ry = min(ry_limit, rx * HEAD_KY)
            self.canvas.coords(self.face_circle, cx - rx, cy - ry, cx + rx, cy + ry)
            self.canvas.itemconfig(self.face_circle, state="normal")
        else:
            self.canvas.itemconfig(self.face_circle, state="hidden")

        # oczy
        l = (cx-eye_dx-eye_w/2, cy-eye_h*blink, cx-eye_dx+eye_w/2, cy+eye_h*blink)
        r = (cx+eye_dx-eye_w/2, cy-eye_h*blink, cx+eye_dx+eye_w/2, cy+eye_h*blink)
        self.canvas.coords(self.eye_l, *l); self.canvas.coords(self.eye_r, *r)

        # pupil helper
        def pup(rect, xoff):
            x1,y1,x2,y2 = rect
            ex = (x1+x2)/2 + xoff
            ey = (y1+y2)/2
            pw = eye_w * 0.18; ph = eye_h * 0.6 * blink + 2
            return (ex-pw/2, ey-ph/2, ex+pw/2, ey+ph/2)

        t = time.time(); freq = 1.2 if model.state in ("wake","record","process") else 2.0
        offL = math.sin(t*freq)*eye_w*0.04 + model.gaze_dx
        offR = math.sin(t*freq+0.35)*eye_w*0.04 + model.gaze_dx
        bias = S*0.017
        self.canvas.coords(self.pupil_l, *pup(l, +bias + offL))
        self.canvas.coords(self.pupil_r, *pup(r, -bias + offR))

        # BRWI
        brow_y = cy - S * 0.16
        brow_w, brow_h = S * 0.19, S * 0.10
        stroke = max(6, int(S * 0.03))
        k_brow = {"idle": 0.12, "wake": 0.08, "record": 0.06, "process": 0.02, "low_battery": 0.18}.get(model.state, 0.08)
        def set_brow(ex: float, arc_item, cap1, cap2, k: float):
            x0, y0 = ex - brow_w/2, brow_y - brow_h
            x1, y1 = ex + brow_w/2, brow_y + brow_h
            if k < 0: start, extent = 20, 140
            else:     start, extent = 200, 140
            self.canvas.coords(arc_item, x0, y0, x1, y1)
            self.canvas.itemconfig(arc_item, start=start, extent=extent, width=stroke)
            if BROW_CAPS:
                for item, ang in ((cap1, start), (cap2, start+extent)):
                    px, py = self._ellipse_point(x0, y0, x1, y1, ang)
                    self.canvas.coords(item, px - stroke/2, py - stroke/2, px + stroke/2, py + stroke/2)
                    self.canvas.itemconfig(item, state="normal")
            else:
                self.canvas.itemconfig(cap1, state="hidden")
                self.canvas.itemconfig(cap2, state="hidden")
        set_brow(cx - eye_dx, self.brow_l, self.brow_l_cap1, self.brow_l_cap2, k_brow)
        set_brow(cx + eye_dx, self.brow_r, self.brow_r_cap1, self.brow_r_cap2, k_brow)

        # USTA
        speaking = (model.assist_speaking or model.state == "speak")
        mouth_w = S * 0.58
        mouth_y = cy + S * 0.235
        if speaking:
            amp = (math.sin(model.speak_phase)+math.sin(model.speak_phase*1.7)*0.6)
            mouth_h = max(8, S * 0.04 + amp * (S * 0.03))
            y = mouth_y; w = mouth_w * (1.0 + 0.06 * max(0.0, amp))
            self.canvas.coords(self.mouth, cx-w/2, y-mouth_h/2, cx+w/2, y+mouth_h/2)
            self.canvas.itemconfig(self.mouth, state="normal")
            self.canvas.itemconfig(self.mouth_arc, state="hidden")
        else:
            k = {"idle": -0.48, "wake": -0.36, "record": -0.28, "process": -0.22, "low_battery": 0.25}.get(model.state, -0.24)
            if model.state != "low_battery" and k >= 0:
                k = -0.18 if k == 0 else -abs(k)
            depth = max(12, int(abs(k) * S * 0.28))
            y = mouth_y
            x0, y0 = cx - mouth_w/2, y - depth
            x1, y1 = cx + mouth_w/2, y + depth
            self.canvas.coords(self.mouth_arc, x0, y0, x1, y1)
            if k < 0: start, extent = 20, 140
            else:     start, extent = 200, 140
            self.canvas.itemconfig(self.mouth_arc, start=start, extent=extent, width=max(8, int(S * 0.055)), state="normal")
            self.canvas.itemconfig(self.mouth, state="hidden")

        t1 = perf_counter()
        self.root.update_idletasks(); self.root.update()
        self._bench_push_ms = (perf_counter() - t1) * 1000.0
        self._bench_draw_ms = (perf_counter() - t0) * 1000.0

    def close(self):
        try: self.root.destroy()
        except Exception: pass

# --- wybór backendu -----------------------------------------------------------
class _Dummy(BaseRenderer):
    def render(self, model: FaceModel): pass
    def close(self): pass

def pick_renderer() -> BaseRenderer:
    if BACKEND_ENV in ("lcd", "led"):
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

# --- app ----------------------------------------------------------------------
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
        self._bench_last_cpu = time.process_time()
        self._bench_last_wall = perf_counter()
        self._bench_frames = 0
        self._dyn_fps = float(FPS)

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
                    evt = ev.get("event", ""); txt = ev.get("text", "")
                    if evt=="start":
                        self.model.assist_speaking=True; self.model.assistant_text=txt; self.model.state="speak"
                    elif evt=="end":
                        self.model.assist_speaking=False; self.model.state="idle"
                elif t=="transcript":
                    self.model.user_text = ev.get("text","")
        except queue.Empty:
            pass

    def _maybe_print_bench(self):
        if not BENCH: return
        self._bench_frames += 1
        now_wall = perf_counter()
        if now_wall - self._bench_last_wall >= 1.0:
            cpu_now = time.process_time()
            wall_dt = now_wall - self._bench_last_wall
            cpu_dt  = cpu_now - self._bench_last_cpu
            fps = self._bench_frames / max(1e-6, wall_dt)
            cpu_pct = 100.0 * cpu_dt / max(1e-6, wall_dt)
            draw_ms = getattr(self.renderer, "_bench_draw_ms", 0.0)
            push_ms = getattr(self.renderer, "_bench_push_ms", 0.0)
            extra = (f" afps~{self._dyn_fps:.1f}" if AUTO_FPS else "")
            print(f"[bench] fps={fps:.1f}  cpu~{cpu_pct:.0f}%  draw={draw_ms:.1f}ms  push={push_ms:.1f}ms{extra}", flush=True)
            self._bench_last_wall = now_wall; self._bench_last_cpu = cpu_now; self._bench_frames = 0

    def run(self):
        dt = 1.0 / max(1, FPS)
        self._dyn_fps = float(FPS)
        try:
            while True:
                t0 = perf_counter()
                self._drain()
                self.model.tick(dt)
                self.renderer.render(self.model)

                if AUTO_FPS:
                    draw_ms = float(getattr(self.renderer, "_bench_draw_ms", 0.0))
                    push_ms = float(getattr(self.renderer, "_bench_push_ms", 0.0))
                    safe_period = max(0.005, (draw_ms + push_ms) / 1000.0 * 1.10)
                    fps_limit = 1.0 / safe_period if safe_period > 0 else float(FPS)
                    target = min(float(FPS), fps_limit)
                    self._dyn_fps = 0.7 * self._dyn_fps + 0.3 * target
                    self._dyn_fps = max(6.0, min(float(FPS), self._dyn_fps))
                    dt = 1.0 / self._dyn_fps

                self._maybe_print_bench()
                elapsed = perf_counter() - t0
                sl = dt - elapsed
                if sl > 0:
                    time.sleep(sl)
        except SystemExit:
            pass
        finally:
            _cleanup(self.renderer)

if __name__ == "__main__":
    FaceApp().run()
