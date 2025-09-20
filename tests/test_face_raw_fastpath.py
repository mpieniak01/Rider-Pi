import json
import os
import subprocess


def run_cli(expr="neutral", rotate=0, fit="fill", force="raw:rgb565"):
    cmd = [
        "python3",
        "tools/face_cli.py",
        "--expr",
        expr,
        "--rotate",
        str(rotate),
        "--fit",
        fit,
        "--force",
        force,
        "--stats",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def test_mock_outputs():
    # Usuń stare pliki
    for ext in [".png", ".rgb565", ".meta.json"]:
        p = f"/tmp/face_last{ext}"
        if os.path.exists(p):
            os.remove(p)
    res = run_cli(expr="happy", rotate=270, fit="fill", force="raw:rgb565")
    assert res.returncode == 0
    # Sprawdź pliki
    for ext in [".png", ".rgb565", ".meta.json"]:
        p = f"/tmp/face_last{ext}"
        assert os.path.exists(p), f"Brak pliku {p}"
    # Sprawdź meta
    with open("/tmp/face_last.meta.json") as f:
        meta = json.load(f)
    assert meta["mode"] == "rgb565"
    assert meta["size"] == [240, 240]
    assert meta["panel"]["rotate"] == 270
    # Sprawdź rozmiar bufora RGB565
    buf = open("/tmp/face_last.rgb565", "rb").read()
    assert len(buf) == 240 * 240 * 2


def test_fit_modes():
    for fit in ["fill", "fit", "stretch"]:
        res = run_cli(expr="sad", rotate=0, fit=fit, force="raw:rgb565")
        assert res.returncode == 0
        with open("/tmp/face_last.meta.json") as f:
            meta = json.load(f)
        assert meta["panel"]["fit"] == fit
