#!/usr/bin/env python3
import os
from PIL import Image, ImageDraw

def rgb565(r,g,b): return ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)

def to_rgb565(img):
    img=img.convert('RGB'); w,h=img.size
    out=bytearray(w*h*2); i=0; px=img.load()
    for y in range(h):
        for x in range(w):
            r,g,b=px[x,y]; v=rgb565(r,g,b)
            out[i]=(v>>8)&0xFF; out[i+1]=v&0xFF; i+=2
    return bytes(out)

def main():
    fb = '/dev/fb1' if os.path.exists('/dev/fb1') else '/dev/fb0'
    W=H=240
    im=Image.new('RGB',(W,H),(255,255,255))
    d=ImageDraw.Draw(im)
    d.rectangle((2,2,W-3,H-3), outline=(0,128,255), width=4)
    data=to_rgb565(im)
    try:
        with open(fb,'wb',buffering=0) as f: f.write(data)
        print('OK: wrote test frame to', fb)
    except Exception as e:
        p='/tmp/lcd_test.png'; im.save(p)
        print('Fallback: saved', p, 'error:', e)

if __name__=='__main__': main()
