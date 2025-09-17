class PanelCfg:
    def __init__(self, rotate: int = 0, bgr: bool = False, mx: bool = False, mv: bool = False):
        self.rotate = rotate
        self.bgr = bgr
        self.mx = mx
        self.mv = mv

    def transform(self, image):
        # Apply rotation
        image = self.apply_rotate(image, self.rotate)
        # Apply BGR/MX/MV transformations if needed
        if self.bgr:
            image = self.convert_to_bgr(image)
        if self.mx:
            image = self.apply_mx_transformation(image)
        if self.mv:
            image = self.apply_mv_transformation(image)
        return image

    def apply_rotate(self, image, deg: int):
        # Implement rotation logic here
        pass

    def convert_to_bgr(self, image):
        # Implement BGR conversion logic here
        pass

    def apply_mx_transformation(self, image):
        # Implement MX transformation logic here
        pass

    def apply_mv_transformation(self, image):
        # Implement MV transformation logic here
        pass