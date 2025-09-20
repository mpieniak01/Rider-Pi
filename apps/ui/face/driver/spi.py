class SpiFaceDriver:
    def __init__(self, cfg):
        self.cfg = cfg

    def push_png(self, img):
        raise NotImplementedError("SPI driver: push_png niezaimplementowane")

    def push_rgb565(self, buf: bytes, w: int, h: int):
        raise NotImplementedError("SPI driver: push_rgb565 niezaimplementowane")
