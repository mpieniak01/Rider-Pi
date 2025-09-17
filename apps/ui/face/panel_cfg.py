from typing import Literal

class PanelCfg:
    def __init__(self, rotate: int = 0, bgr: bool = True, mx: bool = False, mv: bool = False, fit: Literal["fill","fit","stretch"] = "fill"):
        self.rotate = rotate
        self.bgr = bgr
        self.mx = mx
        self.mv = mv
        self.fit = fit
    def as_dict(self):
        return dict(rotate=self.rotate, bgr=self.bgr, mx=self.mx, mv=self.mv, fit=self.fit)
