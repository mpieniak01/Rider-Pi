# WM8960 Sound Card Setup for Rider-Pi Voice Streaming

This guide covers setting up the WM8960 sound card for reliable duplex audio streaming (capture + playback simultaneously).

## ALSA Configuration

### 1. Basic Setup

Copy the provided ALSA configuration to enable duplex operation:

```bash
cp docs/audio/wm8960.asoundrc ~/.asoundrc
```

Or manually create `~/.asoundrc` with the following content:

```
# Dsnoop device for capture (shared input)
pcm.wm8960_in {
    type dsnoop
    ipc_key 1024
    slave {
        pcm "hw:wm8960soundcard,0"
        channels 2
        rate 16000
        format S16_LE
    }
}

# Dmix device for playback (shared output)  
pcm.wm8960_out {
    type dmix
    ipc_key 2048
    slave {
        pcm "hw:wm8960soundcard,0"
        rate 48000
        format S16_LE
        channels 2
    }
}

# Asymmetric default device
pcm.!default {
    type asym
    playback.pcm "wm8960_out"
    capture.pcm  "wm8960_in"
}

# Control device
ctl.!default {
    type hw
    card wm8960soundcard
}
```

### 2. Verification

Test the configuration:

```bash
# Test playback
aplay -D wm8960_out /usr/share/sounds/alsa/Front_Center.wav

# Test capture (record 3 seconds)
arecord -D wm8960_in -d 3 -f S16_LE -r 16000 -c 2 test.wav

# Test simultaneous duplex
arecord -D wm8960_in -f S16_LE -r 16000 -c 2 | aplay -D wm8960_out -f S16_LE -r 48000
```

## Voice Streaming Usage

### Quick Start

```bash
# Kill any conflicting processes
make voice-kill

# Single interaction
make voice-stream-once

# Continuous PTT mode  
make voice-stream-listen
```

### Manual Commands

```bash
# Environment setup
export OPENAI_API_KEY="your-api-key-here"

# Single streaming interaction
python3 -m apps.voice.cli once --mode stream \
  --capture device=wm8960_in sample_rate=16000 channels=2 \
  --playback device=wm8960_out

# Push-to-talk streaming
python3 -m apps.voice.cli ptt --mode stream \
  --capture device=wm8960_in sample_rate=16000 channels=2 \
  --playback device=wm8960_out
```

## Configuration

The voice streaming system is configured via `config/voice.toml`:

### Key Settings

```toml
[capture]
device = "wm8960_in"        # Uses dsnoop alias
sample_rate = 16000         # Required for OpenAI Realtime API
channels = 2                # Hardware stereo, downmixed to mono

[playback]
alsa_device = "wm8960_out"  # Uses dmix alias
volume = 100

[service]
beep = true                 # PTT beep feedback
```

### Audio Processing

The system automatically:
- Converts stereo input to mono using `audioop.tomono()`
- Ensures 16kHz sample rate for API compatibility
- Logs channel conversion: `ch_in=2, ch_out=1`

## Troubleshooting

### No Audio Output
1. Check device availability: `aplay -l | grep wm8960`
2. Test direct playback: `aplay -D wm8960_out test.wav`
3. Verify volume: `amixer -c wm8960soundcard`

### Capture Issues
1. Check permissions: `ls -l /dev/snd/`
2. Test capture: `arecord -D wm8960_in -d 2 test.wav`
3. Kill competing processes: `make voice-kill`

### ALSA Device Busy
```bash
# Find processes using audio devices
lsof /dev/snd/*

# Kill audio processes
make voice-kill

# Reset ALSA state
alsactl init
```

### "Cisza po commit" (Silence After Commit)

This indicates stereo audio was sent instead of mono. Check logs for:
```
event=stream.tx data={"ch_in": 2, "ch_out": 1, "sr": 16000}
```

If `ch_out` is not 1, the downmix failed.

### WebSocket SSL Errors

Look for proper closure logs:
```
event=ws.closing data={"session_id": "..."}  
event=ws.closed data={"session_id": "..."}
```

Missing these indicates improper WebSocket shutdown.

## Diagnostic Commands

```bash
# System audio status
make voice-diag

# Device detection
aplay -l
arecord -l

# Test configuration
arecord -D wm8960_in --dump-hw-params

# Voice system smoke test
make voice-smoke
```

## Performance Notes

- **Capture Rate**: 16kHz for API compatibility
- **Playback Rate**: 48kHz for hardware stability  
- **Chunk Size**: 20ms for low latency
- **Format**: S16_LE (16-bit signed, little-endian)

## Integration with systemd

For production deployment, disable conflicting audio services:

```bash
# Disable PulseAudio (if present)
systemctl --user stop pulseaudio
systemctl --user disable pulseaudio

# Use ALSA directly
systemctl --user enable alsa-state
```

This ensures clean ALSA hardware access for duplex streaming.