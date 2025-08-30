#!/usr/bin/env python3
# common/snap.py
# Prosty „snapper”: zapisuje migawki JPG do katalogu (RAW/PROC/LCD/LCD_FB)
# Sterowanie przez ENV:
#   SNAPSHOT_ENABLE=1        - włącza zapis
#   SNAP_DIR=<path>          - katalog docelowy (domyślnie "./snapshots")
#   SNAP_CAM_EVERY=1         - co ile sekund zapisywać RAW z kamery
#   SNAP_PROC_EVERY=1        - co ile sekund zapisywać obraz po obróbce
#   SNAP_LCD_EVERY=1         - co ile sekund zapisywać „nasz render LCD”
#   SNAP_FB_DEV=/dev/fb1     - urządzenie framebuffer (opcjonalne)
#   SNAP_FB_W=320 SNAP_FB_H=240 - rozmiar FB (jeśli nie wykrywalny)
#
# Powstające pliki:
#   <SNAP_DIR>/cam.jpg
#   <SNAP_DIR>/proc.jpg
#   <SNAP_DIR>/lcd.jpg
#   <SNAP_DIR>/lcd_fb.jpg      (tylko gdy jest framebuffer)

import os, time, mmap, fcntl, struct
from typing import Optional, Dict
import numpy as np
import cv2

class Snapper:
    def __init__(
        self,
        base_dir: Optional[str] = None,
        enable_env: str = "SNAPSHOT_ENABLE",
        cam_every: Optional[float] = None,
        proc_every: Optional[float] = None,
        lcd_every: Optional[float] = None,
    ):
        # konfiguracja
        self._enabled = (os.getenv(enable_env, "0") == "1")
        self.base = os.path.abspath(base_dir or os.getenv("SNAP_DIR", "./snapshots"))
        self._every = {
            "cam":  float(os.getenv("SNAP_CAM_EVERY",  cam_every  if cam_every  is not None else 1.0) or 0),
            "proc": float(os.getenv("SNAP_PROC_EVERY", proc_every if proc_every is not None else 1.0) or 0),
            "lcd":  float(os.getenv("SNAP_LCD_EVERY",  lcd_every  if lcd_every  is not None else 1.0) or 0),
            "lcd_fb": float(os.getenv("SNAP_FB_EVERY", 1.0) or 0),
        }
        self._last: Dict[str, float] = {}
        if self._enabled:
            os.makedirs(self.base, exist_ok=True)

        # FB (opcjonalnie)
        self.fb_dev = os.getenv("SNAP_FB_DEV")  # np. /dev/fb1
        self.fb_w   = int(os.getenv("SNAP_FB_W", "0") or 0)
        self.fb_h   = int(os.getenv("SNAP_FB_H", "0") or 0)
        self.fb_bpp = 16  # najczęściej 16bpp (RGB565) na małych LCD

    # -- helpers -------------------------------------------------------------

    def _should(self, tag: str) -> bool:
        if not self._enabled:
            return False
        every = max(0.0, float(self._every.get(tag, 0.0) or 0.0))
        if every <= 0.0:
            return False
        now = time.time()
        last = self._last.get(tag, 0.0)
        if (now - last) >= every:
            self._last[tag] = now
            return True
        return False

    def _save(self, tag: str, bgr: np.ndarray, fname: Optional[str] = None) -> bool:
        try:
            if bgr is None or bgr.size == 0:
                return False
            path = fname or os.path.join(self.base, f"{tag}.jpg")
            # JPEG z sensowną kompresją
            cv2.imwrite(path, bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            return True
        except Exception:
            return False

    # -- public API ----------------------------------------------------------

    def cam(self, frame_bgr: np.ndarray) -> bool:
        """Zapis RAW z kamery."""
        if not self._should("cam"):
            return False
        return self._save("cam", frame_bgr)

    def proc(self, frame_bgr: np.ndarray) -> bool:
        """Zapis obrazu po obróbce (np. SSD/HAAR/hybrid)."""
        if not self._should("proc"):
            return False
        return self._save("proc", frame_bgr)

    def lcd_from_frame(self, frame_bgr: np.ndarray) -> bool:
        """Zapis tego, co my renderujemy na LCD (z posiadanego obrazu BGR)."""
        if not self._should("lcd"):
            return False
        return self._save("lcd", frame_bgr)

    def lcd_from_pil(self, pil_img) -> bool:
        """
        Zapis dokładnie tego, co zostało przekazane do LCD_2inch.ShowImage(pil_img).
        Użyteczne, gdy podmienimy/owiniemy ShowImage() w previewach.
        """
        if not self._should("lcd"):
            return False
        try:
            rgb = np.array(pil_img)  # PIL RGB -> np.uint8 [H,W,3]
            if rgb.ndim != 3 or rgb.shape[2] != 3:
                return False
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            return self._save("lcd", bgr)
        except Exception:
            return False

    def lcd_from_fb(self) -> bool:
        """
        Zrzut 1:1 z framebuffer’a (np. /dev/fb1) do lcd_fb.jpg.
        Wymaga ustawienia SNAP_FB_DEV (+ ewentualnie SNAP_FB_W/H).
        """
        if not self.fb_dev:
            return False
        if not self._should("lcd_fb"):
            return False
        try:
            # Ustal wymiary: najpierw spróbuj przez ioctl FBIOGET_VSCREENINFO (0x4600)
            w, h, bpp = self.fb_w, self.fb_h, self.fb_bpp
            with open(self.fb_dev, "rb") as f:
                try:
                    # struct fb_var_screeninfo (wycinek: xres,yres,bits_per_pixel - offsety zależne od kernela,
                    # więc bierzemy prosty sposób: jeśli mamy SNAP_FB_W/H to go użyj).
                    if w <= 0 or h <= 0:
                        raise RuntimeError("fb size unknown")
                except Exception:
                    pass

                if w <= 0 or h <= 0:
                    return False

                # Odczyt całej ramki
                frame_len = w * h * (bpp // 8)
                data = f.read(frame_len)
                if len(data) < frame_len:
                    return False

            # Konwersja: RGB565 -> BGR
            if bpp == 16:
                arr = np.frombuffer(data, dtype=np.uint16).reshape((h, w))
                # rozpakowanie RGB565
                r = ((arr >> 11) & 0x1F).astype(np.uint8)
                g = ((arr >> 5)  & 0x3F).astype(np.uint8)
                b = (arr & 0x1F).astype(np.uint8)
                r = (r * 255 // 31).astype(np.uint8)
                g = (g * 255 // 63).astype(np.uint8)
                b = (b * 255 // 31).astype(np.uint8)
                rgb = np.dstack([r, g, b])
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            elif bpp == 24 or bpp == 32:
                # Przy 32bpp często jest ARGB8888 – zignorujemy A.
                arr = np.frombuffer(data, dtype=np.uint8).reshape((h, w, bpp // 8))
                if arr.shape[2] >= 3:
                    # zakładamy kolejność BGRA/ARGB – spróbujmy wydobyć BGR heurystycznie
                    # Weź 3 najmłodsze kanały jako BGR
                    bgr = arr[:, :, :3].copy()
                else:
                    return False
            else:
                return False

            return self._save("lcd_fb", bgr)
        except Exception:
            return False

