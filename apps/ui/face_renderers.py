# -*- coding: utf-8 -*-
"""
apps/ui/face_renderers.py — renderery UI (LCD/Tk) dla buźki Rider-Pi.
 
Zależności:
- Pillow (PIL)
- xgoscreen.LCD_2inch (dla LCDRenderer)

Ten moduł NIE zna się na busie ani stanie aplikacji — przyjmuje FaceConfig
oraz obiekt modelu z polami używanymi w rysowaniu.
"""
from __future__ import annotations
import os, time, math, subprocess
from time import perf_counter
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

# --- Konfiguracja przekazywana do rendererów ---------------------------------
@dataclass
class FaceConfig:
    backend_env: str = "auto"
    fps: int = 30
    bench: bool = True
    guide: bool = True
    brow_caps: bool = False
    brow_style: str = "classic"   # classic | tapered
    quality: str = "fast"          # fast | aa2x (oversampling ×2 dla polygonów)
    brow_taper: float = 0.5        # 0..1 (1=końcówki bardzo wąskie)
    brow_y_k: float = 0.21         # odległość brwi od środka (w jednostkach S)
    brow_h_k: float = 0.09         # wysokość elipsy brwi (kształt łuku)
    mouth_y_k: float = 0.215       # pozycja ust względem środka
    head_ky: float = 1.04          # elipsa głowy (1.0 okrąg)
    lcd_do_init: bool = True
    lcd_rotate: int = 270
    lcd_spi_hz: Optional[int] = None
    lcd_bl_pin: int = 13
    takeover_mode: str = "both"   # off|fuser|pkill|both
    kill_re: str = r"remix\.py|mian\.py|main\.py|demo.*\.py|app_.*\.py"
    colors: Optional[Dict[str, Tuple[int,int,int]]] = None

# --- Helpers: SPI takeover / backlight ---------------------------------------

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pids(pids, label: str):
    me = os.getpid(); ppid = os.getppid(); left = []
    for pid in sorted(set(int(p) for p in pids if str(p).isdigit())):
        if pid in (0, 1, me, ppid):
            continue
        try:
            os.kill(pid, 15)
            left.append(pid)
        except Exception:
            pass
    t0 = time.time()
    while time.time() - t0 < 1.0:
        left = [pid for pid in left if _pid_alive(pid)]
        if not left:
            break
        time.sleep(0.05)
    for pid in left:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
    if pids:
        print(f"[face] takeover({label}): killed {len(pids)} PID(s).", flush=True)


def _takeover(cfg: FaceConfig):
    mode = (cfg.takeover_mode or "off").lower()
    if mode == "off":
        print("[face] takeover=OFF", flush=True)
        return
    if mode in ("fuser", "both"):
        try:
            out = subprocess.check_output(
                [
                    "bash",
                    "-lc",
                    "sudo fuser -v /dev/spidev0.0 /dev/spidev0.1 2>/dev/null | awk 'NF>=2 && $2 ~ /^[0-9]+$/ {print $2}' | sort -u",
                ],
                text=True,
            )
            pids = [int(x) for x in out.strip().splitlines() if x.strip().isdigit()]
            if pids:
                _kill_pids(pids, "fuser"); time.sleep(0.2)
            else:
                print("[face] takeover(fuser): nic nie trzyma SPI.", flush=True)
        except subprocess.CalledProcessError:
            print("[face] takeover(fuser): brak fuser lub brak PIDs.", flush=True)
        except Exception as e:
            print(f"[face] takeover(fuser) warn: {e}", flush=True)
    if mode in ("pkill", "both"):
        try:
            subprocess.run(["sudo", "pkill", "-f", cfg.kill_re], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[face] takeover(pkill): regex wysłany.", flush=True)
            time.sleep(0.2)
        except Exception as e:
            print(f"[face] takeover(pkill) warn: {e}", flush=True)


# --- Renderery ----------------------------------------------------------------
class BaseRenderer:
    _bench_draw_ms: float = 0.0
    _bench_push_ms: float = 0.0
    def render(self, model: Any): ...
    def close(self): ...


class LCDRenderer(BaseRenderer):
    def __init__(self, cfg: FaceConfig):
        self.cfg = cfg
        _takeover(cfg)
        from PIL import Image, ImageDraw  # type: ignore
        # HOTFIX: xgoscreen pwm
        try:
            import xgoscreen.LCD_2inch as LCD_2inch  # type: ignore
            try:
                orig_Init = LCD_2inch.LCD_2inch.Init
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
            except Exception:
                pass
            self.Image, self.ImageDraw = Image, ImageDraw
            self.LCD_2inch = LCD_2inch
        except Exception as e:
            raise RuntimeError(f"xgoscreen import fail: {e}")

        self.display = self.LCD_2inch.LCD_2inch()
        if cfg.lcd_do_init:
            try:
                self.display.Init(); print("[face] LCD: Init()", flush=True)
            except Exception as e:
                print(f"[face] LCD: Init() fail: {e}", flush=True)
        self._force_backlight_on()
        self._apply_spi_hz(cfg.lcd_spi_hz)

        try:
            self.display.clear()
        except Exception:
            pass
        time.sleep(0.2)

        try:
            self.W, self.H = int(self.display.width), int(self.display.height)
        except Exception:
            self.W, self.H = 240, 320
        print(f"[face] LCD: W={self.W} H={self.H}", flush=True)
        print(f"[face] LCD: rotate={cfg.lcd_rotate}", flush=True)
        # Kanwa (CW,CH) to orientacja logiczna przed rotacją sprzętową
        self.CW, self.CH = (self.W, self.H) if cfg.lcd_rotate in (0,180) else (self.H, self.W)

        self.splash = self.Image.new("RGB", (self.CW, self.CH), (0,0,0))
        self.draw = self.ImageDraw.Draw(self.splash)
        self._err_count = 0; self._last_reinit = 0.0

        # start
        self.draw.rectangle([(0,0),(self.CW,self.CH)], fill=(0,120,255))
        self.draw.rectangle([(6,6),(self.CW-6,self.CH-6)], outline=(255,255,255), width=4)
        self._safe_show(self.splash, first=True)

    # --- LCD helpers ---
    def _apply_spi_hz(self, hz: Optional[int]):
        if hz is None: return
        try:
            spi = getattr(self.display, "SPI", None) or getattr(self.display, "spi", None)
            if spi and hasattr(spi, "max_speed_hz"):
                spi.max_speed_hz = int(hz)
                print(f"[face] LCD: spi.max_speed_hz={hz}", flush=True)
        except Exception as e:
            print(f"[face] LCD: SPI speed set fail: {e}", flush=True)

    def set_spi_speed(self, hz: int) -> bool:
        try:
            self._apply_spi_hz(hz); return True
        except Exception:
            return False

    def _force_backlight_on(self):
        try:
            for name in ("bl_DutyCycle", "BL_DutyCycle", "SetBL", "set_bl", "set_backlight"):
                fn = getattr(self.display, name, None)
                if callable(fn):
                    try:
                        fn(100); print("[face] LCD: backlight 100%", flush=True); return
                    except Exception:
                        pass
            import RPi.GPIO as GPIO  # type: ignore
            pin = int(os.environ.get("FACE_LCD_BL_PIN", str(self.cfg.lcd_bl_pin)))
            GPIO.setmode(GPIO.BCM); GPIO.setup(pin, GPIO.OUT); GPIO.output(pin, True)
            print(f"[face] LCD: BL pin {pin}=HIGH", flush=True)
        except Exception as e:
            print(f"[face] LCD: backlight set warn: {e}", flush=True)

    # --- Geometry helpers ---
    def _ellipse_point(self, x0, y0, x1, y1, ang_deg):
        cx = (x0 + x1) / 2.0; cy = (y0 + y1) / 2.0
        rx = (x1 - x0) / 2.0; ry = (y1 - y0) / 2.0
        t = math.radians(ang_deg)
        return (cx + rx * math.cos(t), cy + ry * math.sin(t))

    def _face_geom(self):
        cx, cy = self.CW // 2, self.CH // 2
        S = min(self.CW, self.CH)
        eye_dx = int(S * 0.22)
        eye_w  = int(S * 0.28)
        eye_h  = int(S * 0.12)
        mouth_w = int(S * 0.58)
        mouth_y = int(cy + S * self.cfg.mouth_y_k)
        return cx, cy, eye_dx, eye_w, eye_h, mouth_w, mouth_y

    # --- AA polygon paste helper (for tapered brows in QUALITY=aa2x) ---
    def _paste_polygon_aa(self, pts, fill_rgb=(255,255,255)):
        if self.cfg.quality != "aa2x":
            self.draw.polygon(pts, fill=fill_rgb); return
        from PIL import Image  # lazy
        up = 2
        tmp = Image.new('L', (self.CW*up, self.CH*up), 0)
        d2 = self.ImageDraw.Draw(tmp)
        pts2 = [(int(x*up), int(y*up)) for (x,y) in pts]
        d2.polygon(pts2, fill=255)
        mask = tmp.resize((self.CW, self.CH), resample=Image.LANCZOS)
        color = Image.new('RGB', (self.CW, self.CH), fill_rgb)
        self.splash.paste(color, (0,0), mask)

    def _draw_brow_tapered(self, bbox, start, end, stroke, fill_rgb=(255,255,255)):
        x0,y0,x1,y1 = bbox
        cx = (x0 + x1)/2.0; cy = (y0 + y1)/2.0
        rx = (x1 - x0)/2.0; ry = (y1 - y0)/2.0
        steps = max(16, int(stroke*2))
        if end < start:
            start, end = end, start
        angs = [start + (end-start)*i/(steps-1) for i in range(steps)]
        center_pts = []; normals = []
        for a in angs:
            t = math.radians(a)
            x = cx + rx*math.cos(t); y = cy + ry*math.sin(t)
            nx = (x - cx) / (rx*rx + 1e-6); ny = (y - cy) / (ry*ry + 1e-6)
            norm = math.hypot(nx, ny) or 1.0; nx/=norm; ny/=norm
            center_pts.append((x,y)); normals.append((nx,ny))
        tip_scale = max(0.15, 1.0 - float(self.cfg.brow_taper))
        outer=[]; inner=[]
        for i,(p,(nx,ny)) in enumerate(zip(center_pts, normals)):
            u = i/(len(center_pts)-1 if len(center_pts)>1 else 1)
            w_scale = tip_scale + (1.0 - tip_scale) * math.sin(math.pi*u)
            half = 0.5 * stroke * w_scale
            ox = p[0] + nx*half; oy = p[1] + ny*half
            ix = p[0] - nx*half; iy = p[1] - ny*half
            outer.append((ox,oy)); inner.append((ix,iy))
        pts = outer + inner[::-1]
        self._paste_polygon_aa(pts, fill_rgb=fill_rgb)

    # --- render ---
    def render(self, model: Any):
        t0 = perf_counter(); cfg = self.cfg
        colors = cfg.colors or {"idle": (30,58,138)}
        bg = colors.get(model.state, colors.get("idle", (30,58,138)))
        self.draw.rectangle([(0, 0), (self.CW, self.CH)], fill=bg)

        cx, cy, eye_dx, eye_w, eye_h, mouth_w, mouth_y = self._face_geom()
        blink_mul = model.blink_mul(); S = min(self.CW, self.CH)

        # przewodnik — elipsa
        if cfg.guide:
            M = int(S * 0.04)
            rx_limit = self.CW/2 - M; ry_limit = self.CH/2 - M
            rx = int(min(rx_limit, ry_limit / max(0.001, cfg.head_ky)))
            ry = int(min(ry_limit, rx * cfg.head_ky))
            self.draw.ellipse([(cx - rx, cy - ry), (cx + rx, cy + ry)], outline=(220,235,255), width=2)

        # oczy
        l = (cx - eye_dx - eye_w // 2, cy - int(eye_h * blink_mul), cx - eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
        r = (cx + eye_dx - eye_w // 2, cy - int(eye_h * blink_mul), cx + eye_dx + eye_w // 2, cy + int(eye_h * blink_mul))
        self.draw.ellipse(l, fill=(255,255,255))
        self.draw.ellipse(r, fill=(255,255,255))

        # źrenice
        def pupil_rect(rect, off):
            x1,y1,x2,y2 = rect
            ex, ey = (x1+x2)//2, (y1+y2)//2
            pw = int(eye_w * 0.18); ph = int(eye_h * 0.6 * blink_mul + 2)
            return (ex - pw//2 + off, ey - ph//2, ex + pw//2 + off, ey + ph//2)
        t = time.time(); freq = 1.2 if model.state in ("wake","record","process") else 2.0
        amp = eye_w * 0.04; phase = 0.35; bias = int(S * 0.017)
        offL = int(math.sin(t * freq) * amp + model.gaze_dx)
        offR = int(math.sin(t * freq + phase) * amp + model.gaze_dx)
        self.draw.ellipse(pupil_rect(l,  +bias + offL), fill=(0,0,0))
        self.draw.ellipse(pupil_rect(r,  -bias + offR), fill=(0,0,0))

        # brwi
        brow_y = cy - int(S * cfg.brow_y_k)
        brow_w = int(S * 0.19); brow_h = int(S * cfg.brow_h_k)
        stroke = max(6, int(S * 0.03))
        base_k = {"idle": 0.06, "wake": 0.10, "record": 0.08, "process": 0.04, "low_battery": 0.18}.get(model.state, 0.06)
        if (getattr(model, 'expr', None) or "") == "happy":
            base_k += 0.10 * max(0.0, min(1.0, float(getattr(model, 'expr_intensity', 0.0))))
        def draw_brow_any(ex: int, k: float):
            x0, y0 = ex - brow_w // 2, brow_y - brow_h
            x1, y1 = ex + brow_w // 2, brow_y + brow_h
            if k < 0: start, end = 20, 160    # ∪ (uniesione)
            else:     start, end = 200, 340   # ∩ (zmartwienie)
            bbox = (x0, y0, x1, y1)
            if cfg.brow_style == "tapered":
                self._draw_brow_tapered(bbox, start, end, stroke, fill_rgb=(255,255,255))
            else:
                self.draw.arc([(x0, y0), (x1, y1)], start=start, end=end, fill=(255,255,255), width=stroke)
                if cfg.brow_caps:
                    for ang in (start, end):
                        px, py = self._ellipse_point(x0, y0, x1, y1, ang)
                        self.draw.ellipse([(px - stroke/2, py - stroke/2), (px + stroke/2, py + stroke/2)], fill=(255,255,255))
        draw_brow_any(cx - eye_dx, base_k)
        draw_brow_any(cx + eye_dx, base_k)

        # usta
        def mouth_curvature_for(state: str) -> float:
            k = {"idle": -0.48, "wake": -0.36, "record": -0.28, "process": -0.22, "low_battery": 0.25, "speak": -0.18}.get(state, -0.24)
            if state != "low_battery" and k >= 0:
                k = -0.18 if k == 0 else -abs(k)
            if (getattr(model, 'expr', None) or "") == "happy":
                k -= 0.18 * max(0.0, min(1.0, float(getattr(model, 'expr_intensity', 0.0))))
            if (getattr(model, 'expr', None) or "") == "neutral":
                k = -0.18
            return k
        def draw_mouth_curve(cx_i: int, y: int, w: int, k: float) -> None:
            Sloc = S
            depth = max(6, int(abs(k) * Sloc * 0.28))
            x0, y0, x1, y1 = cx_i - w // 2, y - depth, cx_i + w // 2, y + depth
            if k < 0: start, end = 20, 160   # ∪ (uśmiech)
            else:     start, end = 200, 340  # ∩ (smutek)
            self.draw.arc([(x0, y0), (x1, y1)], start=start, end=end, fill=(0,0,0), width=max(8, int(Sloc * 0.055)))
        if getattr(model, 'assist_speaking', False) or model.state == "speak":
            amp_m = (math.sin(model.speak_phase) + math.sin(model.speak_phase*1.7)*0.6)
            height = max(6, int(S * 0.04) + int(amp_m * (S * 0.03)))
            width  = int(mouth_w * (1.0 + 0.06 * max(0.0, amp_m)))
            self.draw.rectangle([(cx - width//2, mouth_y - height//2), (cx + width//2, mouth_y + height//2)], fill=(0,0,0))
        else:
            draw_mouth_curve(cx, mouth_y, mouth_w, mouth_curvature_for(model.state))

        self._bench_draw_ms = (perf_counter() - t0) * 1000.0
        self._safe_show(self.splash)

    def _safe_show(self, img, first=False):
        t1 = perf_counter()
        try:
            if img.size != (self.CW, self.CH):
                img = img.resize((self.CW, self.CH))
            rot = self.cfg.lcd_rotate
            from PIL import Image
            if rot in (90, 270):
                # PIL ROTATE_90 = +90° counter-clockwise; rider używa 270 zwykle
                img = img.transpose(Image.ROTATE_90 if rot==90 else Image.ROTATE_270)
            elif rot == 180:
                img = img.transpose(Image.ROTATE_180)
            if img.size != (self.W, self.H):
                img = img.resize((self.W, self.H))
            try:
                buf = self.display.getbuffer(img)  # type: ignore[attr-defined]
            except Exception:
                buf = img
            self.display.ShowImage(buf)
            self._bench_push_ms = (perf_counter() - t1) * 1000.0
            self._err_count = 0
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
            self._force_backlight_on(); self._apply_spi_hz(self.cfg.lcd_spi_hz)
            print("[face] LCD: reinit done", flush=True)
            self._err_count = 0
        except Exception as e:
            print(f"[face] LCD: reinit failed: {e}", flush=True)

    def close(self):
        try:
            if hasattr(self.display, "module_exit"):
                self.display.module_exit()
        except Exception:
            pass


class TKRenderer(BaseRenderer):
    def __init__(self, cfg: FaceConfig):
        import tkinter as tk
        self.cfg = cfg
        self.tk = tk
        self.root = tk.Tk(); self.root.title("Rider-Pi Face")
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

    def render(self, model: Any):
        t0 = perf_counter(); cfg = self.cfg
        colors = cfg.colors or {"idle": (30,58,138)}
        base = colors.get(model.state, colors.get("idle", (30,58,138)))
        self.canvas.itemconfig(self.bg, fill="#%02x%02x%02x" % base)

        cx, cy = self.W/2, self.H/2
        S = min(self.W, self.H)
        eye_dx, eye_w, eye_h = S*0.22, S*0.28, S*0.12
        blink = model.blink_mul()

        # przewodnik — elipsa
        if cfg.guide:
            M = int(S * 0.04)
            rx_limit = self.W/2 - M; ry_limit = self.H/2 - M
            rx = min(rx_limit, ry_limit / max(0.001, cfg.head_ky))
            ry = min(ry_limit, rx * cfg.head_ky)
            self.canvas.coords(self.face_circle, cx - rx, cy - ry, cx + rx, cy + ry)
            self.canvas.itemconfig(self.face_circle, state="normal")
        else:
            self.canvas.itemconfig(self.face_circle, state="hidden")

        # oczy
        l = (cx-eye_dx-eye_w/2, cy-eye_h*blink, cx-eye_dx+eye_w/2, cy+eye_h*blink)
        r = (cx+eye_dx-eye_w/2, cy-eye_h*blink, cx+eye_dx+eye_w/2, cy+eye_h*blink)
        self.canvas.coords(self.eye_l, *l); self.canvas.coords(self.eye_r, *r)

        # źrenice
        def pup(rect, xoff):
            x1,y1,x2,y2 = rect
            ex = (x1+x2)/2 + xoff; ey = (y1+y2)/2
            pw = eye_w * 0.18; ph = eye_h * 0.6 * blink + 2
            return (ex-pw/2, ey-ph/2, ex+pw/2, ey+ph/2)
        t = time.time(); freq = 1.2 if model.state in ("wake","record","process") else 2.0
        offL = math.sin(t*freq)*eye_w*0.04 + model.gaze_dx
        offR = math.sin(t*freq+0.35)*eye_w*0.04 + model.gaze_dx
        bias = S*0.017
        self.canvas.coords(self.pupil_l, *pup(l, +bias + offL))
        self.canvas.coords(self.pupil_r, *pup(r, -bias + offR))

        # BRWI
        brow_y = cy - S * cfg.brow_y_k
        brow_w, brow_h = S * 0.19, S * cfg.brow_h_k
        stroke = max(6, int(S * 0.03))
        base_k = {"idle": 0.06, "wake": 0.10, "record": 0.08, "process": 0.04, "low_battery": 0.18}.get(model.state, 0.06)
        if (getattr(model, 'expr', None) or "") == "happy":
            base_k += 0.10 * max(0.0, min(1.0, float(getattr(model, 'expr_intensity', 0.0))))
        def set_brow(ex: float, arc_item, cap1, cap2, k: float):
            x0, y0 = ex - brow_w/2, brow_y - brow_h
            x1, y1 = ex + brow_w/2, brow_y + brow_h
            if k < 0: start, extent = 20, 140
            else:     start, extent = 200, 140
            self.canvas.coords(arc_item, x0, y0, x1, y1)
            self.canvas.itemconfig(arc_item, start=start, extent=extent, width=stroke)
            if cfg.brow_caps:
                for item, ang in ((cap1, start), (cap2, start+extent)):
                    px = (x0+x1)/2 + (x1-x0)/2 * math.cos(math.radians(ang))
                    py = (y0+y1)/2 + (y1-y0)/2 * math.sin(math.radians(ang))
                    self.canvas.coords(item, px - stroke/2, py - stroke/2, px + stroke/2, py + stroke/2)
                    self.canvas.itemconfig(item, state="normal")
            else:
                self.canvas.itemconfig(cap1, state="hidden"); self.canvas.itemconfig(cap2, state="hidden")
        set_brow(cx - eye_dx, self.brow_l, self.brow_l_cap1, self.brow_l_cap2, base_k)
        set_brow(cx + eye_dx, self.brow_r, self.brow_r_cap1, self.brow_r_cap2, base_k)

        # USTA
        speaking = (getattr(model,'assist_speaking',False) or model.state == "speak")
        mouth_w = S * 0.58; mouth_y = cy + S * cfg.mouth_y_k
        if speaking:
            amp = (math.sin(model.speak_phase)+math.sin(model.speak_phase*1.7)*0.6)
            mouth_h = max(8, S * 0.04 + amp * (S * 0.03))
            y = mouth_y; w = mouth_w * (1.0 + 0.06 * max(0.0, amp))
            self.canvas.coords(self.mouth, cx-w/2, y-mouth_h/2, cx+w/2, y+mouth_h/2)
            self.canvas.itemconfig(self.mouth, state="normal"); self.canvas.itemconfig(self.mouth_arc, state="hidden")
        else:
            k = {"idle": -0.48, "wake": -0.36, "record": -0.28, "process": -0.22, "low_battery": 0.25}.get(model.state, -0.24)
            if (getattr(model, 'expr', None) or "") == "happy":
                k -= 0.18 * max(0.0, min(1.0, float(getattr(model, 'expr_intensity', 0.0))))
            if (getattr(model, 'expr', None) or "") == "neutral":
                k = -0.18
            depth = max(12, int(abs(k) * S * 0.28))
            y = mouth_y
            x0, y0 = cx - mouth_w/2, y - depth
            x1, y1 = cx + mouth_w/2, y + depth
            self.canvas.coords(self.mouth_arc, x0, y0, x1, y1)
            if k < 0: start, extent = 20, 140
            else:     start, extent = 200, 140
            self.canvas.itemconfig(self.mouth_arc, start=start, extent=extent, width=max(8, int(S * 0.055)), state="normal")
            self.canvas.itemconfig(self.mouth, state="hidden")

        t1 = perf_counter(); self.root.update_idletasks(); self.root.update()
        self._bench_push_ms = (perf_counter() - t1) * 1000.0
        self._bench_draw_ms = (perf_counter() - t0) * 1000.0

    def close(self):
        try: self.root.destroy()
        except Exception: pass

