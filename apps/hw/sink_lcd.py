# -*- coding: utf-8 -*-
"""
apps/hw/sink_lcd.py — obsługa wyświetlacza LCD dla buźki Rider-Pi.
Dwie ścieżki: RAW (push_rgb565) i fallback (show_image PIL.Image).
Rotacja tylko w sinku (ENV: FACE_LCD_ROTATE), domyślnie 270°.
"""
import os
from PIL import Image


import struct

class SinkLCD:
    def __init__(self, width=240, height=320, rotate=None, spi_hz=None, spi_dev=None, method="auto"):
        self.width = width
        self.height = height
        self.rotate = int(rotate) if rotate is not None else int(os.environ.get("LCD_ROTATE", 270))
        self.spi_hz = int(spi_hz) if spi_hz is not None else int(os.environ.get("SPI_HZ", 32000000))
        self.spi_dev = spi_dev or os.environ.get("LCD_SPI_DEV", "/dev/spidev0.0")
        self.method = method or os.environ.get("LCD_METHOD", "auto")
        self._spi = None
        self._init_spi()

    def _init_spi(self):
        try:
            import spidev
            self._spi = spidev.SpiDev()
            bus, dev = self._parse_spi_dev(self.spi_dev)
            self._spi.open(bus, dev)
            self._spi.max_speed_hz = self.spi_hz
        except Exception as e:
            print(f"[sink_lcd] SPI init fail: {e}")
            self._spi = None

    def _parse_spi_dev(self, devstr):
        # /dev/spidev0.0 → (0,0)
        try:
            base = os.path.basename(devstr)
            if base.startswith("spidev"):
                bus, dev = base.replace("spidev", "").split(".")
                return int(bus), int(dev)
        except Exception:
            pass
        return 0, 0


    def push_rgb565(self, w, h, data: bytes):
        """
        Szybka ścieżka: wysyła surowe dane RGB565 do LCD przez SPI.
        :param w: szerokość
        :param h: wysokość
        :param data: bajty RGB565 (w*h*2)
        """
        if self._spi is None:
            raise RuntimeError("SPI not initialized")
        self._spi.writebytes(data)

    def push_frame_rgb565_3(self, w, h, data: bytes):
        """
        Alternatywna ścieżka: packed 3-bajtowe (np. do niestandardowego protokołu).
        :param w: szerokość
        :param h: wysokość
        :param data: bajty (w*h*3)
        """
        if self._spi is None:
            raise RuntimeError("SPI not initialized")
        self._spi.writebytes(data)

    def push_auto(self, img: Image.Image):
        """
        Wybiera metodę na podstawie self.method lub auto.
        """
        img = self._apply_rotation(img)
        img = img.convert("RGB").resize((self.width, self.height))
        arr = img.tobytes()
        if self.method == "rgb565" or (self.method == "auto"):
            rgb565 = self._rgb888_to_rgb565(arr)
            try:
                self.push_rgb565(self.width, self.height, rgb565)
                return "rgb565"
            except Exception as e:
                print(f"[sink_lcd] push_rgb565 failed: {e}")
                if self.method == "rgb565":
                    raise
        if self.method == "rgb565_3" or (self.method == "auto"):
            rgb565_3 = self._rgb888_to_rgb565_3(arr)
            try:
                self.push_frame_rgb565_3(self.width, self.height, rgb565_3)
                return "rgb565_3"
            except Exception as e:
                print(f"[sink_lcd] push_frame_rgb565_3 failed: {e}")
                if self.method == "rgb565_3":
                    raise
        # Fallback
        self.show_image(img)
        return "pil"

    def _rgb888_to_rgb565_3(self, arr: bytes) -> bytes:
        # Przykładowa konwersja: 3 bajty na piksel (R,G,B) packed
        return arr

    def show_image(self, img: Image.Image):
        """
        Fallback: wyświetla obraz PIL.Image na LCD (np. przez starszy sterownik).
        :param img: PIL.Image
        """
        print("[sink_lcd] Fallback: ShowImage(PIL)")
        # Tu można podpiąć starszy sterownik, np. xgoscreen.LCD_2inch
        # raise NotImplementedError lub zaimplementować jeśli dostępne
        pass

    def _rgb888_to_rgb565(self, arr: bytes) -> bytes:
        # Konwersja RGB888 (PIL) → RGB565
        out = bytearray()
        for i in range(0, len(arr), 3):
            r, g, b = arr[i], arr[i+1], arr[i+2]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out.append((v >> 8) & 0xFF)
            out.append(v & 0xFF)
        return bytes(out)

    def _apply_rotation(self, img: Image.Image) -> Image.Image:
        if self.rotate == 270:
            return img.transpose(Image.ROTATE_270)
        elif self.rotate == 90:
            return img.transpose(Image.ROTATE_90)
        elif self.rotate == 180:
            return img.transpose(Image.ROTATE_180)
        return img

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
