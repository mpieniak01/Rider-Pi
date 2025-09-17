import argparse
import os
from apps.ui.face.driver import make_driver
from apps.ui.face.panel_cfg import PanelCfg

def main():
    parser = argparse.ArgumentParser(description="Face LCD CLI")
    parser.add_argument('--expr', choices=['neutral', 'happy', 'sad', 'blink'], required=True, help='Expression to display')
    parser.add_argument('--rotate', choices=[0, 90, 180, 270], type=int, default=0, help='Rotation angle')
    parser.add_argument('--spi-hz', type=int, help='SPI frequency in Hz')
    parser.add_argument('--fit', choices=['fill', 'fit', 'stretch'], default='fill', help='Fit strategy for the image')
    parser.add_argument('--force', choices=['raw:rgb565', 'push_frame:rgb565_3', 'png'], required=True, help='Force mode for image processing')
    parser.add_argument('--stats', action='store_true', help='Display statistics')

    args = parser.parse_args()

    # Load configuration from environment variables or use defaults
    rotate = os.getenv('FACE_LCD_ROTATE', args.rotate)
    spi_hz = os.getenv('FACE_LCD_SPI_HZ', args.spi_hz)
    fit = os.getenv('FACE_LCD_FIT', args.fit)

    # Create panel configuration
    panel_cfg = PanelCfg(rotate=rotate, bgr=True, mx=False, mv=False)

    # Create driver
    driver = make_driver(kind=os.getenv('FACE_LCD_BACKEND', 'mock'), cfg=panel_cfg)

    # Process the expression and display it using the driver
    # This part would include the logic to convert the expression to an image
    # and then push it to the driver. For now, it's a placeholder.
    image = None  # Placeholder for the image generated from the expression
    if args.force == 'raw:rgb565':
        # Convert image to RGB565 and push
        rgb565_data = driver.push_rgb565(image, width, height)
    elif args.force == 'push_frame:rgb565_3':
        # Fallback method
        driver.push_rgb565(image, width, height)
    elif args.force == 'png':
        # Push as PNG
        driver.push_png(image)

    if args.stats:
        # Display statistics if requested
        print("Statistics: ...")  # Placeholder for statistics

if __name__ == "__main__":
    main()