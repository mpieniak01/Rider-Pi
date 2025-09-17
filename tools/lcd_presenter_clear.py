#!/usr/bin/env python3
import os, sys, importlib
from PIL import Image

# środowisko (Hz/mode nie są wymagane przez ShowImage, ale ustawiamy jeśli się da)
SPI_HZ  = int(os.getenv("FACE_LCD_SPI_HZ","0") or 0)
SPI_MODE= int(os.getenv("FACE_SPI_MODE","0") or 0)

sys.path[:0]=['/home/pi/robot','/home/pi/robot/apps']
xs = importlib.import_module('xgoscreen')

# Znajdź klasę/obiekt z ShowImage
dev = None
for name in dir(xs):
    obj = getattr(xs, name)
    # 1) bezpośrednio obiekty z ShowImage
    if hasattr(obj, 'ShowImage') and callable(getattr(obj, 'ShowImage')):
        try:
            dev = obj()  # konstruktor bez parametrów
            break
        except Exception:
            pass

# 2) skanuj podmoduły xgoscreen.*
if dev is None:
    import pkgutil, importlib
    for _, modname, _ in pkgutil.walk_packages(xs.__path__, xs.__name__ + '.'):
        try:
            m = importlib.import_module(modname)
        except Exception:
            continue
        for name in dir(m):
            c = getattr(m, name)
            if getattr(c, '__name__', '').lower().find('lcd') >= 0 and hasattr(c, 'ShowImage'):
                try:
                    dev = c()
                    break
                except Exception:
                    continue
        if dev: break

if dev is None:
    raise SystemExit("Nie znalazłem klasy z ShowImage w xgoscreen.*")

# Init/Begin jeśli istnieje
for meth in ('begin','Begin','Init','init'):
    fn = getattr(dev, meth, None)
    if callable(fn):
        try: fn()
        except Exception: pass

# Ustaw tryb SPI (jeśli sterownik to wystawia)
spi = getattr(dev, 'SPI', None)
if spi is not None:
    try:
        if SPI_HZ:  spi.max_speed_hz = SPI_HZ
        if hasattr(spi,'mode'): spi.mode = SPI_MODE
    except Exception:
        pass

# Rozmiar
W = getattr(dev, 'width', 240); H = getattr(dev, 'height', 320)

# Czarny kadr i do urządzenia
img = Image.new("RGB", (W,H), "black")
dev.ShowImage(img)
print(f"[presenter] cleared to black, W={W} H={H}, hz={SPI_HZ} mode={SPI_MODE}")
