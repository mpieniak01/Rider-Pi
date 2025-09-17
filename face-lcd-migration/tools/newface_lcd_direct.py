import argparse
import os
from apps.ui.face.driver import make_driver
from apps.ui.face.panel_cfg import PanelCfg

def main():
    parser = argparse.ArgumentParser(description="Face LCD Direct Interface")
    parser.add_argument('--expr', type=str, choices=['neutral', 'happy', 'sad', 'blink'], required=True, help='Expression to display')
    parser.add_argument('--rotate', type=int, choices=[0, 90, 180, 270], default=0, help='Rotation angle')
    parser.add_argument('--spi-hz', type=int, help='SPI frequency in Hz')
    parser.add_argument('--fit', type=str, choices=['fill', 'fit', 'stretch'], default='fill', help='Fit strategy for the image')
    parser.add_argument('--force', type=str, choices=['raw:rgb565', 'push_frame:rgb565_3', 'png'], required=True, help='Force mode for image processing')
    parser.add_argument('--stats', action='store_true', help='Display statistics')

    args = parser.parse_args()

    # Load panel configuration
    panel_cfg = PanelCfg(rotate=args.rotate)

    # Create driver based on environment variable or default to mock
    backend = os.getenv('FACE_LCD_BACKEND', 'mock')
    driver = make_driver(backend, panel_cfg)

    # Process the expression and display it using the driver
    # This part would include the logic to generate the image based on the expression
    # and then push it to the driver. For now, we will just print the arguments.
    
    print(f"Expression: {args.expr}")
    print(f"Rotation: {args.rotate}")
    print(f"SPI Hz: {args.spi_hz}")
    print(f"Fit strategy: {args.fit}")
    print(f"Force mode: {args.force}")
    print(f"Stats: {args.stats}")

if __name__ == "__main__":
    main()