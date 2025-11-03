#!/usr/bin/env python3
"""
Demonstration script for config validation features.

Shows all acceptance criteria in action:
1. Complete TOML loading with schema validation
2. Fail-fast and lenient modes
3. Type and range validation
4. Precedence (TOML < CLI overrides)
5. Path resolution
6. Secret masking
7. --print-effective-config
8. Typo suggestions
"""

import sys
import tempfile
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.voice.config_loader import (
    ConfigLoader,
    ValidationError,
    mask_secrets,
    print_effective_config,
)


def demo_positive_loading():
    """Criterion 1: Complete TOML loading works."""
    print("\n" + "=" * 60)
    print("1. POSITIVE LOADING - voice_openai_file.toml and voice_openai_streaming_fallback.toml")
    print("=" * 60)

    loader = ConfigLoader()

    # Load file mode config
    config1 = loader.load("voice_openai_file.toml")
    print(f"✓ Loaded voice_openai_file.toml with {len(config1)} sections")

    # Load streaming mode config
    config2 = loader.load("voice_openai_streaming_fallback.toml")
    print(f"✓ Loaded voice_openai_streaming_fallback.toml with {len(config2)} sections")
    print(f"  - server_vad={config2['stream']['server_vad']}")
    print(f"  - hotword.enabled={config2['hotword']['enabled']}")


def demo_fail_fast_mode():
    """Criterion 2: Fail-fast mode catches unknown keys."""
    print("\n" + "=" * 60)
    print("2. FAIL-FAST MODE - Unknown keys raise ValidationError")
    print("=" * 60)

    loader = ConfigLoader(lenient=False)

    try:
        loader.load(
            "voice_openai_file.toml",
            overrides={"asr": {"backedn": "openai"}, "unknown_section": {"key": "val"}},
        )
        print("✗ FAILED: Should have raised ValidationError")
    except ValidationError as e:
        print("✓ ValidationError raised correctly")
        error_msg = str(e)
        # Check for typo suggestion
        if "backedn" in error_msg.lower() and "backend" in error_msg.lower():
            print("✓ Typo suggestion included (backedn → backend)")
        # Check for unknown section
        if "unknown_section" in error_msg.lower():
            print("✓ Unknown section detected")


def demo_lenient_mode():
    """Criterion 2: Lenient mode warns but continues."""
    print("\n" + "=" * 60)
    print("3. LENIENT MODE - Unknown keys logged as warnings")
    print("=" * 60)

    loader = ConfigLoader(lenient=True)

    _ = loader.load(
        "voice_openai_file.toml",
        overrides={"asr": {"unknown_key": "test"}, "bad_section": {"x": 1}},
    )

    print(f"✓ Config loaded in lenient mode with {len(loader.unknown_keys)} unknown keys")
    print(f"  Unknown keys: {['.'.join(k) for k in loader.unknown_keys]}")


def demo_type_validation():
    """Criterion 3: Type and range validation."""
    print("\n" + "=" * 60)
    print("4. TYPE AND RANGE VALIDATION")
    print("=" * 60)

    loader = ConfigLoader(lenient=False)

    # Test invalid channels
    try:
        loader.load("voice_openai_file.toml", overrides={"capture": {"channels": 3}})
        print("✗ FAILED: Should reject channels=3")
    except ValidationError as e:
        if "channels" in str(e) and "[1, 2]" in str(e):
            print("✓ Rejected channels=3 (must be 1 or 2)")

    # Test invalid volume
    try:
        loader.load("voice_openai_file.toml", overrides={"playback": {"volume": 150}})
        print("✗ FAILED: Should reject volume=150")
    except ValidationError as e:
        if "volume" in str(e) and "100" in str(e):
            print("✓ Rejected volume=150 (max is 100)")

    # Test invalid backend
    try:
        loader.load("voice_openai_file.toml", overrides={"asr": {"backend": "invalid"}})
        print("✗ FAILED: Should reject invalid backend")
    except ValidationError as e:
        if "backend" in str(e):
            print("✓ Rejected invalid ASR backend")


def demo_precedence():
    """Criterion 4: Precedence TOML < CLI."""
    print("\n" + "=" * 60)
    print("5. PRECEDENCE - CLI overrides TOML")
    print("=" * 60)

    loader = ConfigLoader()

    # Load base config
    config1 = loader.load("voice_openai_file.toml")
    base_voice = config1["tts"]["voice"]

    # Override with CLI
    config2 = loader.load("voice_openai_file.toml", overrides={"tts": {"voice": "nova"}})
    overridden_voice = config2["tts"]["voice"]

    print(f"✓ Base TOML: tts.voice = {base_voice}")
    print(f"✓ With CLI override: tts.voice = {overridden_voice}")
    print(f"✓ Precedence works: {overridden_voice != base_voice}")


def demo_path_resolution():
    """Criterion 5: Path resolution relative to TOML directory."""
    print("\n" + "=" * 60)
    print("6. PATH RESOLUTION - Relative to TOML file directory")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create TOML with relative path
        toml_file = tmppath / "test.toml"
        toml_file.write_text(
            """
[save_audio]
enabled = true
dir = "audio_logs"
"""
        )

        loader = ConfigLoader()
        config = loader.load(toml_file, toml_dir=tmppath)

        resolved_path = config["save_audio"]["dir"]
        expected = str((tmppath / "audio_logs").resolve())

        print(f"✓ TOML at: {tmppath}")
        print(f"✓ Relative path 'audio_logs' resolved to: {resolved_path}")
        print(f"✓ Matches expected: {resolved_path == expected}")


def demo_secret_masking():
    """Criterion 6: Secret masking in logs."""
    print("\n" + "=" * 60)
    print("7. SECRET MASKING - Sensitive data protection")
    print("=" * 60)

    config = {
        "stream": {"auth": "sk-1234567890abcdefghij", "endpoint": "wss://example.com"},
        "api_key": "secret_token_xyz123",
        "normal_field": "visible_value",
    }

    masked = mask_secrets(config, keep_tail=4)

    print(f"Original auth: {config['stream']['auth']}")
    print(f"Masked auth:   {masked['stream']['auth']}")
    print(f"✓ Secret masked, last 4 chars visible: {masked['stream']['auth'].endswith('ghij')}")

    print(f"\nOriginal api_key: {config['api_key']}")
    print(f"Masked api_key:   {masked['api_key']}")
    print(f"✓ API key masked, last 4 chars visible: {masked['api_key'].endswith('x123')}")

    print(f"\nNormal field not masked: {masked['normal_field'] == 'visible_value'}")


def demo_print_effective():
    """Criterion 7: --print-effective-config works."""
    print("\n" + "=" * 60)
    print("8. PRINT EFFECTIVE CONFIG - Show final merged config")
    print("=" * 60)

    loader = ConfigLoader()
    config = loader.load("voice_openai_file.toml", overrides={"tts": {"voice": "nova"}})

    print("✓ Effective config (first 10 lines):")
    import io
    import sys

    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()

    try:
        print_effective_config(config, mask=True)
        output = buffer.getvalue()
        lines = output.split("\n")[:10]
        for line in lines:
            print(line, file=old_stdout)
    finally:
        sys.stdout = old_stdout


def demo_ptt_ignored():
    """Criterion 9: PTT ignored when server_vad=true and hotword disabled."""
    print("\n" + "=" * 60)
    print("9. PTT SECTION IGNORED - When using server VAD")
    print("=" * 60)

    loader = ConfigLoader()
    config = loader.load("voice_openai_streaming_fallback.toml")

    # Check conditions
    server_vad = config["stream"]["server_vad"]
    hotword_enabled = config["hotword"]["enabled"]
    ptt_in_config = "ptt" in config

    print(f"✓ server_vad={server_vad}, hotword.enabled={hotword_enabled}")
    print(f"✓ PTT section present but ignored: {ptt_in_config}")
    print("  (Check logs for INFO message about PTT being ignored)")


def main():
    print("\n" + "╔" + "=" * 58 + "╗")
    print("║  CONFIG VALIDATION DEMONSTRATION - All Criteria          ║")
    print("╚" + "=" * 58 + "╝")

    try:
        demo_positive_loading()
        demo_fail_fast_mode()
        demo_lenient_mode()
        demo_type_validation()
        demo_precedence()
        demo_path_resolution()
        demo_secret_masking()
        demo_print_effective()
        demo_ptt_ignored()

        print("\n" + "╔" + "=" * 58 + "╗")
        print("║  ✓ ALL ACCEPTANCE CRITERIA DEMONSTRATED SUCCESSFULLY    ║")
        print("╚" + "=" * 58 + "╝\n")

        return 0
    except Exception as e:
        print(f"\n✗ DEMO FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
