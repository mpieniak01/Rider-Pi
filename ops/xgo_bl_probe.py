#!/usr/bin/env python3
import inspect, re
try:
    import xgoscreen.LCD_2inch as LCD_2inch
except Exception as e:
    print("Import fail:", e); raise SystemExit(1)

lcd = LCD_2inch.LCD_2inch(); lcd.Init()
print("LCD attrs:", [n for n in dir(lcd) if not n.startswith("_")][:20], "...")
mods = [lcd, LCD_2inch, getattr(LCD_2inch, "config", None)]
for m in mods:
    if not m: continue
    print("\n== scan in", m.__class__ if hasattr(m,"__class__") else m)
    for n in dir(m):
        try: a = getattr(m,n)
        except Exception: continue
        if callable(a):
            low = n.lower()
            if ("init" in low and ("bl" in low or "pwm" in low or "backlight" in low)) or ("duty" in low and "bl" in low):
                print("CALL:", n)
        else:
            if n in ("BL","Backlight","BACKLIGHT","LCD_BL","PIN_BL") or n.lower() in ("bl","backlight","lcd_bl","pin_bl"):
                print("ATTR pin:", n, "=", getattr(m,n))
print("\nTry: bl_DutyCycle(10) -> 80 if present")
fn = getattr(lcd, "bl_DutyCycle", None)
if callable(fn):
    try:
        fn(10); import time; time.sleep(1); fn(80); print("OK")
    except Exception as e:
        print("bl_DutyCycle error:", e)
else:
    print("no bl_DutyCycle")