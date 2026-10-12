"""Hardware defaults for this Rider CM4 board; no GPIO/SPI I/O on import."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LCDBoard:
    bl: int = 0
    rst: int = 27
    dc: int = 25
    rotate: int = 270
    spi: str = "/dev/spidev0.0"
    hz: int = 12_000_000


def lcd_board():
    def integer(primary, legacy, default):
        return int(os.getenv(primary, os.getenv(legacy, str(default))))

    board = LCDBoard(
        bl=integer("FACE_LCD_BL_PIN", "LCD_BL_GPIO", 0),
        rst=integer("FACE_LCD_RST_PIN", "RST_PIN", 27),
        dc=integer("FACE_LCD_DC_PIN", "DC_PIN", 25),
        rotate=integer("FACE_LCD_ROTATE", "SPLASH_ROTATE", 270),
        spi=os.getenv("FACE_LCD_SPI_DEV", os.getenv("SPI_DEV", "/dev/spidev0.0")),
        hz=integer("FACE_LCD_SPI_HZ", "SPI_HZ", 12_000_000),
    )
    if any(not 0 <= pin <= 27 for pin in (board.bl, board.rst, board.dc)):
        raise ValueError("invalid_lcd_board_pin")
    if board.rotate not in {0, 90, 180, 270} or not re.fullmatch(r"/dev/spidev\d+\.\d+", board.spi):
        raise ValueError("invalid_lcd_board_config")
    if not 1 <= board.hz <= 62_500_000:
        raise ValueError("invalid_lcd_spi_hz")
    return board
