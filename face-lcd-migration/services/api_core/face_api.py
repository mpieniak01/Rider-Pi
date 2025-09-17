# face_api.py

from flask import Flask, jsonify, request
from apps.ui.face.driver import make_driver
from apps.ui.face.panel_cfg import PanelCfg

app = Flask(__name__)

@app.route('/face', methods=['POST'])
def push_face():
    data = request.json
    expression = data.get('expr')
    rotate = data.get('rotate', 0)
    spi_hz = data.get('spi_hz', 32000000)
    fit = data.get('fit', 'fill')
    backend = data.get('backend', 'mock')

    cfg = PanelCfg(rotate=rotate, bgr=False, mx=False, mv=False)
    driver = make_driver(kind=backend, cfg=cfg)

    # Here you would typically process the image based on the expression
    # For now, we will just simulate the push
    image = None  # Placeholder for the actual image processing logic

    if backend == 'mock':
        driver.push_png(image)
        return jsonify({"status": "success", "message": "Image pushed to mock backend."}), 200
    else:
        return jsonify({"status": "error", "message": "Unsupported backend."}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)