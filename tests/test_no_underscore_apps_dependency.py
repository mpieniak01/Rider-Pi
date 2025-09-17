import os
import re
import pytest

# Pliki, które nie mogą importować _apps
CHECK_PATHS = [
    "apps/ui/face/",
    "services/api_core/face_api.py",
    "tools/newface_lcd_direct.py",
    "tools/face_cli.py",
]

IMPORT_RE = re.compile(r"^\s*from _apps|^\s*import _apps|_apps/ui/face_renderers.py")

def scan_file(path):
    with open(path) as f:
        for i, line in enumerate(f, 1):
            if IMPORT_RE.search(line):
                return (i, line.strip())
    return None

def collect_py_files(base):
    if os.path.isfile(base):
        return [base] if base.endswith(".py") else []
    out = []
    for root, dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(root, f))
    return out

@pytest.mark.parametrize("path", sum([collect_py_files(p) for p in CHECK_PATHS], []))
def test_no_underscore_apps(path):
    res = scan_file(path)
    assert res is None, f"Zabroniony import _apps w {path}:{res}"
