#!/usr/bin/env python3
"""Check for imports of legacy/deprecated files that should not be used.

This guard prevents reintroduction of code patterns that were refactored away.

Legacy files blocked:
  - apps/voice/audio/* (to be migrated to top-level modules)
  - apps/voice/ws_transport.py (removed in PR-1)
  - apps/voice/stream_transport.py (removed in PR-1)
  - apps/voice/service_impl.py (removed in PR-1, moved to svc_file.py)
  - apps/voice/capture.py (removed in PR-3, use apps.voice.audio.capture)
  - apps/voice/playback.py (removed in PR-3, use apps.voice.audio.playback)
  - apps/voice/state.py (removed in PR-3, use apps.voice.stream.state)
  - apps/voice/svc_stream.py (removed in PR-3)
  - apps/voice/ptt_state.py (removed in PR-3)
  - apps/voice/transport.py (removed in PR-4, use apps.voice.stream.transport)
  - apps/voice/stream/service.py (renamed to svc_streaming.py)
  - apps/voice/audio/wavutil.py (removed - dead code)
  - apps/voice/audio_rx_tts.py (removed - dead code)
  - apps/voice/audio_tx.py (removed - dead code)
  - apps/voice/ding.py (removed - dead code)
  - apps/voice/svc_file_pipeline.py (removed - dead code)
  - apps/voice/voice_metrics.py (removed - dead code)
  - apps/voice/main.py (moved to _todelete, use apps.voice.cli)
  - apps/ui/face_*.py (moved to _todelete, use apps.draw or apps.ui.face)
  - apps/ui/face/driver_ili9xx.py (moved to _todelete, use drivers.lcd.driver_ili9xx)
  - apps/launcher/main.py (moved to _todelete, duplicate of apps/menu/main.py)

Exit codes:
  0 - No legacy imports found
  1 - Legacy imports detected
"""

import re
import sys
from pathlib import Path

# Patterns for legacy imports to block
LEGACY_PATTERNS = [
    # Files removed in PR-1
    (
        r"from apps\.voice\.ws_transport\b",
        "apps/voice/ws_transport.py (removed in PR-1)",
    ),
    (
        r"from apps\.voice\.stream_transport\b",
        "apps/voice/stream_transport.py (removed in PR-1)",
    ),
    (
        r"from apps\.voice\.service_impl\b",
        "apps/voice/service_impl.py (removed in PR-1, use apps.voice.svc_file)",
    ),
    (
        r"import apps\.voice\.ws_transport\b",
        "apps/voice/ws_transport.py (removed in PR-1)",
    ),
    (
        r"import apps\.voice\.stream_transport\b",
        "apps/voice/stream_transport.py (removed in PR-1)",
    ),
    (
        r"import apps\.voice\.service_impl\b",
        "apps/voice/service_impl.py (removed in PR-1, use apps.voice.svc_file)",
    ),
    # Files removed in PR-3 (audio/state modules)
    (
        r"from apps\.voice\.capture\b",
        "apps/voice/capture.py (removed in PR-3, use apps.voice.audio.capture)",
    ),
    (
        r"from apps\.voice\.playback\b",
        "apps/voice/playback.py (removed in PR-3, use apps.voice.audio.playback)",
    ),
    (
        r"import apps\.voice\.capture\b",
        "apps/voice/capture.py (removed in PR-3, use apps.voice.audio.capture)",
    ),
    (
        r"import apps\.voice\.playback\b",
        "apps/voice/playback.py (removed in PR-3, use apps.voice.audio.playback)",
    ),
    # Files removed in earlier PR-3 (shims)
    (
        r"from apps\.voice\.svc_stream\b",
        "apps/voice/svc_stream.py (removed in PR-3, use svc_stream_runner or stream.svc_streaming)",
    ),
    (
        r"from apps\.voice\.state\b",
        "apps/voice/state.py (removed in PR-3, use apps.voice.stream.state)",
    ),
    (
        r"from apps\.voice\.ptt_state\b",
        "apps/voice/ptt_state.py (removed in PR-3, use apps.voice.stream.state)",
    ),
    (r"import apps\.voice\.svc_stream\b", "apps/voice/svc_stream.py (removed in PR-3)"),
    (r"import apps\.voice\.state\b", "apps/voice/state.py (removed in PR-3)"),
    (r"import apps\.voice\.ptt_state\b", "apps/voice/ptt_state.py (removed in PR-3)"),
    # Mixins removed in PR-3
    (
        r"\bStreamingVoiceTransportMixin\b",
        "StreamingVoiceTransportMixin (removed in PR-3)",
    ),
    (r"\bStreamingVoicePTTMixin\b", "StreamingVoicePTTMixin (removed in PR-3)"),
    # Files removed in PR-4 (transport consolidation)
    (
        r"from apps\.voice\.transport\b",
        "apps/voice/transport.py (removed in PR-4, use apps.voice.stream.transport)",
    ),
    (
        r"import apps\.voice\.transport\b",
        "apps/voice/transport.py (removed in PR-4, use apps.voice.stream.transport)",
    ),
    # Files removed in refactor PR (dead code)
    (
        r"from apps\.voice\.stream\.service\b",
        "apps/voice/stream/service.py (renamed to svc_streaming.py)",
    ),
    (
        r"from apps\.voice\.audio\.wavutil\b",
        "apps/voice/audio/wavutil.py (removed - dead code)",
    ),
    (
        r"from apps\.voice\.audio_rx_tts\b",
        "apps/voice/audio_rx_tts.py (removed - dead code)",
    ),
    (r"from apps\.voice\.audio_tx\b", "apps/voice/audio_tx.py (removed - dead code)"),
    (
        r"from apps\.voice\.ding\b",
        "apps/voice/ding.py (removed - dead code, use playback.play_ding)",
    ),
    (
        r"from apps\.voice\.svc_file_pipeline\b",
        "apps/voice/svc_file_pipeline.py (removed - dead code)",
    ),
    (
        r"from apps\.voice\.voice_metrics\b",
        "apps/voice/voice_metrics.py (removed - dead code)",
    ),
    (
        r"import apps\.voice\.audio\.wavutil\b",
        "apps/voice/audio/wavutil.py (removed - dead code)",
    ),
    (
        r"import apps\.voice\.audio_rx_tts\b",
        "apps/voice/audio_rx_tts.py (removed - dead code)",
    ),
    (r"import apps\.voice\.audio_tx\b", "apps/voice/audio_tx.py (removed - dead code)"),
    (r"import apps\.voice\.ding\b", "apps/voice/ding.py (removed - dead code)"),
    (
        r"import apps\.voice\.svc_file_pipeline\b",
        "apps/voice/svc_file_pipeline.py (removed - dead code)",
    ),
    (
        r"import apps\.voice\.voice_metrics\b",
        "apps/voice/voice_metrics.py (removed - dead code)",
    ),
    # Files moved to _todelete in refactor PR (orphaned stubs)
    (
        r"from apps\.voice\.main\b",
        "apps/voice/main.py (moved to _todelete, use apps.voice.cli)",
    ),
    (
        r"import apps\.voice\.main\b",
        "apps/voice/main.py (moved to _todelete, use apps.voice.cli)",
    ),
    (
        r"from apps\.ui\.face_actuators\b",
        "apps/ui/face_actuators.py (moved to _todelete, use apps.draw)",
    ),
    (
        r"from apps\.ui\.face_core\b",
        "apps/ui/face_core.py (moved to _todelete, use apps.draw)",
    ),
    (
        r"from apps\.ui\.face_emotions\b",
        "apps/ui/face_emotions.py (moved to _todelete, use apps.draw)",
    ),
    (
        r"from apps\.ui\.splash_face\b",
        "apps/ui/splash_face.py (moved to _todelete, use apps.draw)",
    ),
    (
        r"from apps\.ui\.tts2face\b",
        "apps/ui/tts2face.py (moved to _todelete, use apps.draw)",
    ),
    (
        r"from apps\.ui\.face\.driver_ili9xx\b",
        "apps/ui/face/driver_ili9xx.py (moved to _todelete, use drivers.lcd)",
    ),
    (
        r"from apps\.launcher\.main\b",
        "apps/launcher/main.py (moved to _todelete, use apps.menu.main)",
    ),
    (
        r"import apps\.launcher\.main\b",
        "apps/launcher/main.py (moved to _todelete, use apps.menu.main)",
    ),
]

# Audio directory imports - warn but don't fail (to be migrated in future)
AUDIO_IMPORT_PATTERN = r"from apps\.voice\.audio\b"
AUDIO_IMPORT_MSG = "apps/voice/audio/* (deprecated, pending migration to top-level)"


def check_file_for_legacy_imports(file_path: Path) -> list[tuple[int, str, str]]:
    """Check a single file for legacy imports.

    Args:
        file_path: Path to the Python file

    Returns:
        List of (line_number, line_text, reason) tuples for violations
    """
    violations = []

    try:
        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                # Skip comments and blank lines
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                # Check for legacy patterns
                for pattern, reason in LEGACY_PATTERNS:
                    if re.search(pattern, line):
                        violations.append((line_num, line.rstrip(), reason))

    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return violations


def check_file_for_audio_imports(file_path: Path) -> list[tuple[int, str]]:
    """Check for audio/* imports (warning only).

    Args:
        file_path: Path to the Python file

    Returns:
        List of (line_number, line_text) tuples
    """
    audio_imports = []

    try:
        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                if re.search(AUDIO_IMPORT_PATTERN, line):
                    audio_imports.append((line_num, line.rstrip()))

    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return audio_imports


def main():
    """Main entry point."""
    repo_root = Path(__file__).parent.parent

    # Check all Python files in the repo (except _apps)
    python_files = []
    for pattern in [
        "apps/**/*.py",
        "tests/**/*.py",
        "common/**/*.py",
        "services/**/*.py",
    ]:
        python_files.extend(repo_root.glob(pattern))

    # Filter out excluded directories
    excluded = {"_apps"}
    python_files = [f for f in python_files if not any(part in excluded for part in f.parts)]

    failures = []
    warnings = []

    for file_path in sorted(python_files):
        # Check for hard-blocked legacy imports
        violations = check_file_for_legacy_imports(file_path)
        if violations:
            rel_path = file_path.relative_to(repo_root)
            for line_num, line_text, reason in violations:
                failures.append((rel_path, line_num, line_text, reason))

        # Check for audio/* imports (warning only, unless it's in audio/ itself)
        if "audio" not in file_path.parts:
            audio_imports = check_file_for_audio_imports(file_path)
            if audio_imports:
                rel_path = file_path.relative_to(repo_root)
                for line_num, line_text in audio_imports:
                    warnings.append((rel_path, line_num, line_text))

    # Report warnings for audio/* imports
    if warnings:
        print("⚠️  Deprecated imports found (audio/* directory):")
        print()
        for rel_path, line_num, line_text in warnings:
            print(f"  {rel_path}:{line_num}")
            print(f"    {line_text}")
            print(f"    → {AUDIO_IMPORT_MSG}")
            print()

    # Report failures for blocked legacy imports
    if failures:
        print("❌ Legacy imports detected:")
        print()
        for rel_path, line_num, line_text, reason in failures:
            print(f"  {rel_path}:{line_num}")
            print(f"    {line_text}")
            print(f"    → {reason}")
            print()

        print(f"{len(failures)} legacy import(s) found.")
        print("\nPlease update imports to use the refactored modules.")
        return 1

    if warnings:
        print(f"✅ No hard-blocked legacy imports (but {len(warnings)} audio/* import(s) should be migrated)")
    else:
        print(f"✅ No legacy imports found (checked {len(python_files)} files)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
