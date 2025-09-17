"""
Fabryka driverów LCD buźki: mock (domyślny), spi (opcjonalny).
"""
from typing import Literal, Optional
from .mock import MockFaceDriver
try:
	from .spi import SpiFaceDriver
except ImportError:
	SpiFaceDriver = None

from apps.ui.face.panel_cfg import PanelCfg

class Driver:
	def push_png(self, img):
		raise NotImplementedError
	def push_rgb565(self, buf: bytes, w: int, h: int):
		raise NotImplementedError

def make_driver(kind: Literal["mock", "spi"], cfg: PanelCfg) -> Driver:
	if kind == "mock":
		return MockFaceDriver(cfg)
	elif kind == "spi":
		if SpiFaceDriver is None:
			raise RuntimeError("SPI driver not available")
		return SpiFaceDriver(cfg)
	else:
		raise ValueError(f"Unknown driver kind: {kind}")