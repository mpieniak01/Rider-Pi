#!/usr/bin/env python3
"""
tools/face_ng.py — nowy CLI do renderowania buźki Codex.
Parametry: --expr, --fps, --sink, --rotate
"""
import argparse
import time
import io
from apps.ui.face.renderer import FaceRenderer
from apps.hw.sink_lcd import SinkLCD
from PIL import Image

class DummyFaceState:
    def __init__(self, expr):
        self.state = expr
        self.expr = expr
        self.expr_intensity = 0.0
        self.gaze_dx = 0
        self.assist_speaking = False
        self.speak_phase = 0.0
    def blink_mul(self):
        return 1.0

def main():
    parser = argparse.ArgumentParser(description="Renderuj buźkę Codex na LCD, PNG lub plik.")
    parser.add_argument('--expr', type=str, default='neutral', help='Wyraz twarzy (happy|sad|neutral)')
    parser.add_argument('--fps', type=float, default=1.0, help='Liczba klatek na sekundę (default: 1)')
    parser.add_argument('--sink', type=str, default='png', help='Wyjście: lcd|png (default: png)')
    parser.add_argument('--rotate', type=int, default=270, help='Rotacja LCD (default: 270)')
    parser.add_argument('--spi_hz', type=int, default=None, help='Częstotliwość SPI (np. 32000000)')
    parser.add_argument('--spi_dev', type=str, default=None, help='Urządzenie SPI (np. /dev/spidev0.0)')
    parser.add_argument('--method', type=str, default='auto', help='Metoda LCD: auto|rgb565|rgb565_3|pil')
    parser.add_argument('--out', type=str, default='face_ng.png', help='Plik wyjściowy PNG (dla sink=png)')
    parser.add_argument('--animate', type=str, default='', help='Animacja: idle (mruganie, ruchy oczu)')
    args = parser.parse_args()

    cfg = type("Cfg", (), {"mouth_y_k": 0.215, "brow_y_k": 0.21, "brow_h_k": 0.09, "head_ky": 1.04})()
    renderer = FaceRenderer(cfg, size=240)
    state = DummyFaceState(args.expr)

    # --- Animacja idle ---
    import random
    next_blink = time.time() + random.uniform(10, 20) if args.animate == 'idle' else None
    next_eye = time.time() + random.uniform(2, 4) if args.animate == 'idle' else None

    def render_and_sink():
        png_bytes = renderer.render_png_bytes(state)
        if args.sink == 'lcd':
            lcd = SinkLCD(width=240, height=240, rotate=args.rotate, spi_hz=args.spi_hz, spi_dev=args.spi_dev, method=args.method)
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB").resize((240, 240))
            used = lcd.push_auto(img)
            print(f'Wysłano klatkę do LCD (metoda: {used})')
        elif args.sink == 'png':
            with open(args.out, 'wb') as f:
                f.write(png_bytes)
            print(f'Zapisano do pliku: {args.out}')
        else:
            print('Render OK (PNG bytes, brak wyjścia)')

    if args.fps <= 0.0:
        render_and_sink()
    else:
        delay = 1.0 / args.fps
        frame_count = 0
        t_start = time.time()
        try:
            while True:
                t0 = time.time()
                now = time.time()
                # --- Animacja idle ---
                if args.animate == 'idle':
                    # Mruganie 3–6/min
                    if now >= next_blink:
                        state._blink_until = now + 0.12
                        next_blink = now + random.uniform(10, 20)
                    if hasattr(state, '_blink_until') and now < getattr(state, '_blink_until', 0):
                        state._blink = 1.0
                    else:
                        state._blink = 0.0
                    # Ruchy oczu co 2–4 s
                    if now >= next_eye:
                        state.gaze_dx = random.randint(-10, 10)
                        next_eye = now + random.uniform(2, 4)
                # Nadpisz blink_mul()
                def blink_mul():
                    return getattr(state, '_blink', 0.0) * 0.75 + 1.0 - 0.75 * getattr(state, '_blink', 0.0)
                state.blink_mul = blink_mul
                render_and_sink()
                frame_count += 1
                dt = time.time() - t0
                if dt < delay:
                    time.sleep(delay - dt)
                # FPS log co 2 sekundy
                if frame_count % 40 == 0:
                    elapsed = time.time() - t_start
                    fps = frame_count / elapsed if elapsed > 0 else 0
                    print(f"[face_ng] FPS: {fps:.2f}")
        except KeyboardInterrupt:
            print('Przerwano.')

if __name__ == '__main__':
    main()
