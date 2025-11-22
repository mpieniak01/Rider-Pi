# Config Validation and Schema Enforcement

## Overview

The Voice Assistant configuration system now includes comprehensive validation with schema enforcement, providing:

- **Fail-fast validation** (default) - catches typos and invalid values early
- **Lenient mode** - warns about unknown keys but continues execution  
- **Type and range checking** - ensures values are valid before runtime
- **Secret masking** - protects sensitive data in logs
- **Effective config printing** - see exactly what configuration will be used

## Quick Start

### Basic Usage

```bash
# Use default config (config/voice.toml)
python -m apps.voice.cli listen

# Specify custom config file
python -m apps.voice.cli --config config/voice_openai_file.toml listen

# Print effective configuration (merged TOML + ENV + CLI)
python -m apps.voice.cli --config config/voice_openai_file.toml --print-effective-config
```

### Validation Modes

**Fail-Fast (Default)** - Stops on any unknown key or invalid value:
```bash
# This will fail with helpful error message
python -m apps.voice.cli --config myconfig.toml listen --asr unknown_key=test
# Output: Configuration error: Unknown key 'asr.unknown_key'. Did you mean 'backend'?
```

**Lenient Mode** - Warns but continues:
```bash
# This will log warnings but continue
python -m apps.voice.cli --config-lenient --config myconfig.toml listen --asr unknown_key=test
# Output: WARNING: Unknown config key 'asr.unknown_key'
```

## Configuration Schema

### Supported Sections

All configuration must be organized into these sections:

- `[logging]` - Log level and output settings
- `[capture]` - Audio input (microphone) configuration
- `[playback]` - Audio output (speaker) configuration
- `[asr]` - Automatic Speech Recognition settings
- `[nlu]` - Natural Language Understanding (optional)
- `[chat]` - Chat/LLM backend configuration
- `[tts]` - Text-to-Speech settings
- `[hotword]` - Wake word detection
- `[ptt]` - Push-to-Talk configuration
- `[stream]` - Streaming/WebSocket settings
- `[vad]` - Voice Activity Detection
- `[turn]` - Turn-taking and timing
- `[service]` - Service-level settings
- `[save_audio]` - Audio logging/debugging

### Type and Range Validation

The system validates:

**Enums** - Must be one of allowed values:
```toml
[capture]
channels = 1  # Valid: 1 or 2
channels = 3  # ERROR: must be one of [1, 2]

[asr]
backend = "openai"    # Valid
backend = "invalid"   # ERROR: must be one of ["openai", "vosk", "whisper"]
```

**Ranges** - Numeric values within bounds:
```toml
[playback]
volume = 75     # Valid: 0-100
volume = 150    # ERROR: must be <= 100

[ptt]
silence_ms = 700     # Valid: 100-5000
silence_ms = 50      # ERROR: must be >= 100
```

**Types** - Correct data types:
```toml
[hotword]
enabled = true       # Valid: boolean
enabled = "yes"      # ERROR: must be bool, got str
```

## Configuration Precedence

Configuration sources are applied in this order (later overrides earlier):

1. **Default values** - Built-in schema defaults
2. **TOML file** - Values from config file
3. **Environment variables** - `VOICE_*` prefixed vars
4. **CLI arguments** - Command-line overrides

Example:
```toml
# config/myvoice.toml
[tts]
voice = "alloy"
```

```bash
# ENV overrides TOML
export VOICE_TTS_VOICE="nova"

# CLI overrides ENV and TOML
python -m apps.voice.cli --config config/myvoice.toml listen --tts voice=ash
# Effective: voice = "ash"
```

## Secret Masking

Sensitive values are automatically masked in logs and `--print-effective-config`:

```toml
[stream]
auth = "env:OPENAI_API_KEY"  # Value: sk-1234567890abcdef...
```

Masked output:
```
[stream]
auth = "***************cdef"  # Last 4 chars visible
```

Fields masked automatically:
- Any field containing: `key`, `token`, `secret`, `password`, `auth`

## Path Resolution

Relative paths in config are resolved relative to the TOML file directory:

```toml
# In /home/user/config/voice.toml
[save_audio]
dir = "audio_logs"  # Becomes: /home/user/config/audio_logs

# Or use absolute paths
dir = "/var/log/rider/audio"

# Or home directory expansion
dir = "~/rider/audio"  # Becomes: /home/user/rider/audio
```

## Effective Configuration

Print the final merged configuration:

```bash
python -m apps.voice.cli \
  --config config/voice_openai_file.toml \
  --print-effective-config \
  listen \
  --asr model=whisper-large \
  --tts voice=nova
```

Output shows complete TOML with all precedence applied and secrets masked.

## Error Messages

The system provides helpful error messages:

**Unknown Key with Typo Suggestion:**
```
Configuration error:
Unknown key 'asr.backedn'. Did you mean 'asr.backend'?
```

**Invalid Value:**
```
Configuration error:
Field 'capture.channels' must be one of [1, 2], got '3'
```

**Multiple Errors:**
```
Configuration validation failed:

Unknown keys:
  - asr.unknown_field
  - chat.bad_param

Validation errors:
  - Field 'playback.volume' must be <= 100, got 150
  - Field 'capture.backend' must be one of ["alsa", "arecord", "pyaudio"], got "invalid"
```

## Special Cases

### PTT with Server VAD

When using server-side Voice Activity Detection in streaming mode:

```toml
[hotword]
enabled = false

[stream]
server_vad = true

[ptt]
# This section is ignored (logged as INFO)
commit_on_stop = true
```

The system will log: `INFO: [ptt] section is ignored when hotword.enabled=false and stream.server_vad=true`

## Migration from Legacy Config

If you have existing configs without validation:

1. **Run with `--print-effective-config`** to see current state
2. **Fix any validation errors** (typos, invalid values)
3. **Use `--config-lenient`** temporarily during migration
4. **Remove lenient mode** once all configs are clean

Example migration:
```bash
# Step 1: See what's wrong
python -m apps.voice.cli --config old.toml --print-effective-config 2>&1 | tee issues.txt

# Step 2: Run in lenient mode while fixing
python -m apps.voice.cli --config-lenient --config old.toml listen

# Step 3: Fix all warnings, then remove --config-lenient
python -m apps.voice.cli --config old.toml listen
```

## Complete Example

Minimal valid configuration:

```toml
# config/minimal.toml
[capture]
device = "wm8960_in"
rate = 16000
channels = 1

[playback]
device = "wm8960_out"
backend = "aplay"

[asr]
backend = "openai"

[chat]
backend = "openai"
model = "gpt-4o-mini"

[tts]
format = "wav"
voice = "alloy"
```

With validation:
```bash
# Validate and print
python -m apps.voice.cli --config config/minimal.toml --print-effective-config

# Run with validation
python -m apps.voice.cli --config config/minimal.toml listen
```

## Best Practices

1. **Always validate new configs** with `--print-effective-config` before deploying
2. **Use lenient mode only during migration** - fix issues, don't ignore them
3. **Keep secrets in ENV vars**, not in TOML files
4. **Use relative paths** for portability when possible
5. **Test with fail-fast mode** to catch issues early

## Reference

For complete list of all configuration options, see:
- [voice.md](voice.md) - Voice configuration reference
- [Voice config examples](.) - Example TOML files

For schema details, see: `apps/voice/config_loader.py`
