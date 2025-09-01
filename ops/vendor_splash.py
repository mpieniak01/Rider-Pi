#!/usr/bin/env python3
import os, time, sys
from PIL import Image, ImageDraw, ImageFont
try:
    import xgoscreen.LCD_2inch as LCD_2inch
except Exception as e:
    print("Brak xgoscreen.LCD_2inch:", e); sys.exit(1)

disp = LCD_2inch.LCD_2inch()
disp.Init(); disp.clear()

# Spróbuj odczytać rozmiar z drivera
W = int(getattr(disp, 'W', getattr(disp, 'width', 240)))
H = int(getattr(disp, 'H', getattr(disp, 'height', 320)))

img = Image.new("RGB", (W, H), (15, 21, 46))
d = ImageDraw.Draw(img)

# 3 „kafelki” jak u producenta
pad=20
third=(W-4*pad)//3
for i,x0 in enumerate([pad, pad+third+pad, pad+2*(third+pad)]):
    d.rectangle([(x0, H- (H//2)), (x0+third, H-pad)], fill=(15,21,46))

# Napisy
try:
    font2 = ImageFont.truetype("/home/pi/model/msyh.ttc", 20)
except Exception:
    font2 = ImageFont.load_default()

title = "DEVICE INFO"
tw = d.textlength(title, font=font2)
d.text(((W-tw)/2, 20), title, fill="white", font=font2)

# Odśwież
disp.ShowImage(img)
time.sleep(3)
