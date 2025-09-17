from PIL import Image
from typing import Literal

def to_rgb565(img: Image) -> bytes:
    """Convert a PIL Image to RGB565 format."""
    img = img.convert("RGB")
    rgb565 = bytearray()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = img.getpixel((x, y))
            rgb565.append((r >> 3) << 3)  # R
            rgb565.append(((g >> 2) << 5) | (b >> 3))  # G and B
    return bytes(rgb565)

def apply_rotate(img: Image, deg: int) -> Image:
    """Rotate the image by the specified degrees."""
    return img.rotate(deg, expand=True)

def fit_strategy(img: Image, mode: Literal["fill", "fit", "stretch"]) -> Image:
    """Fit the image according to the specified strategy."""
    if mode == "fill":
        return img  # No resizing, just return the original image
    elif mode == "fit":
        # Resize while maintaining aspect ratio
        img.thumbnail((img.width, img.height), Image.ANTIALIAS)
        return img
    elif mode == "stretch":
        # Stretch to fit the specified dimensions
        return img.resize((img.width, img.height), Image.ANTIALIAS)
    else:
        raise ValueError("Invalid fit mode specified.")