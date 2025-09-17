def make_driver(kind: str, cfg: 'PanelCfg') -> 'Driver':
    if kind == "mock":
        from .mock import MockDriver
        return MockDriver(cfg)
    elif kind == "spi":
        from .spi import SpiDriver
        return SpiDriver(cfg)
    else:
        raise ValueError(f"Unknown driver kind: {kind}")

class Driver:
    def push_png(self, img: 'Image'):
        raise NotImplementedError

    def push_rgb565(self, data: bytes, w: int, h: int):
        raise NotImplementedError