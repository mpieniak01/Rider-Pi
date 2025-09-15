#!/usr/bin/env python3
"""
tools/face_ng.py — nowy CLI do renderowania buźki Codex.
Parametry: --expr, --fps, --sink, --rotate
"""
import argparse
import time
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
    parser.add_argument('--sink', type=str, default='none', help='Wyjście: lcd|file|none (default: none)')
    parser.add_argument('--rotate', type=int, default=270, help='Rotacja LCD (default: 270)')
    parser.add_argument('--file', type=str, default='face_ng.png', help='Plik wyjściowy (dla sink=file)')
    args = parser.parse_args()

    cfg = type("Cfg", (), {"mouth_y_k": 0.215, "brow_y_k": 0.21, "brow_h_k": 0.09, "head_ky": 1.04})()
    renderer = FaceRenderer(cfg, size=240)
    state = DummyFaceState(args.expr)

    def render_and_sink():
        png_bytes = renderer.render_png_bytes(state)
        if args.sink == 'lcd':
            lcd = SinkLCD(width=240, height=240, rotate=args.rotate)
            img = Image.open(io.BytesIO(png_bytes))
            lcd.show_image(img)
        elif args.sink == 'file':
            with open(args.file, 'wb') as f:
                f.write(png_bytes)
            print(f'Zapisano do pliku: {args.file}')
        else:
            print('Render OK (PNG bytes, brak wyjścia)')

    if args.fps <= 0.0:
        render_and_sink()
    else:
        delay = 1.0 / args.fps
        try:
            while True:
                t0 = time.time()
                render_and_sink()
                dt = time.time() - t0
                if dt < delay:
                    time.sleep(delay - dt)
        except KeyboardInterrupt:
            print('Przerwano.')

if __name__ == '__main__':
    main()
