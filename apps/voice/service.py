from __future__ import annotations

import os

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.route("/capture", methods=["POST"])
def capture_route():
    """Capture audio and run ASR."""
    try:
        sec = float(request.args.get("sec", 1.0))
    except Exception:
        sec = -1.0
    from .capture import capture
    body, code = capture(sec)
    return jsonify(body), code


@app.route("/say", methods=["POST"])
def say_route():
    """Speak text via TTS."""
    data = request.get_json(silent=True) or {}
    from .tts import say
    body, code = say(data)
    return jsonify(body), code


def main():
    bind = os.getenv("VOICE_BIND", "127.0.0.1:8092")
    host, port = bind.split(":")
    app.run(host=host, port=int(port), debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
