# -*- coding: utf-8 -*-
"""
apps/hw/sink_lcd.py — obsługa wyświetlacza LCD dla buźki Rider-Pi.
Dwie ścieżki: RAW (push_rgb565) i fallback (show_image PIL.Image).
Rotacja tylko w sinku (ENV: FACE_LCD_ROTATE), domyślnie 270°.
"""
import os
from PIL import Image

class SinkLCD:
    def __init__(self, width=240, height=320, rotate=None, spi_hz=None):
        self.width = width
        self.height = height
        self.rotate = int(rotate) if rotate is not None else int(os.environ.get("FACE_LCD_ROTATE", 270))
        self.spi_hz = spi_hz
        # TODO: Inicjalizacja sprzętu LCD (np. przez xgoscreen lub inny sterownik)

    def push_rgb565(self, w, h, data: bytes):
        """
        Szybka ścieżka: wysyła surowe dane RGB565 do LCD.
        :param w: szerokość
        :param h: wysokość
        :param data: bajty RGB565 (w*h*2)
        """
        # TODO: Implementacja zależna od sterownika LCD
        raise NotImplementedError("push_rgb565: implementacja zależna od sprzętu")

    def show_image(self, img: Image.Image):
        """
        Fallback: wyświetla obraz PIL.Image na LCD (konwersja + rotacja).
        :param img: PIL.Image
        """
        img = self._apply_rotation(img)
        # TODO: Implementacja wyświetlania obrazu na LCD
        raise NotImplementedError("show_image: implementacja zależna od sprzętu")

    def _apply_rotation(self, img: Image.Image) -> Image.Image:
        if self.rotate == 270:
            return img.transpose(Image.ROTATE_270)
        elif self.rotate == 90:
            return img.transpose(Image.ROTATE_90)
        elif self.rotate == 180:
            return img.transpose(Image.ROTATE_180)
        return img
