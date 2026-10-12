"""Goal metadata must not load capture/VAD implementations."""

import ast
from pathlib import Path


def test_voice_package_imports_no_audio_implementation_at_startup():
    path = Path(__file__).resolve().parents[2] / "apps/voice/__init__.py"
    root = ast.parse(path.read_text())
    imports = [node for node in root.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(getattr(node, "module", None) in {"__future__", "importlib"} for node in imports)


def test_public_errors_keep_their_original_identity():
    from apps.voice import BackpressureExceeded, VoiceError
    from apps.voice.errors import BackpressureExceeded as Original

    assert BackpressureExceeded is Original
    assert issubclass(BackpressureExceeded, VoiceError)
