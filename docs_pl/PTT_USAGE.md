# PTT (Push-to-Talk) Mode Usage

## Overview

The PTT (Push-to-Talk) mode allows you to control voice interactions using the ENTER key. This provides precise control over when the system listens to your voice input.

## Usage

### Basic PTT Mode

```bash
# Using streaming mode (recommended)
./voice ptt --mode stream

# Using file mode (traditional pipeline)
./voice ptt --mode file
```

### With ALSA cleanup (if devices are busy)

```bash
./voice ptt --mode stream --force
```

## Interaction Flow

1. **Ready State (IDLE)**
   - System displays: `ui.state: idle`
   - Press ENTER to start recording

2. **Recording (RECORDING)**
   - First press of ENTER activates recording
   - System displays: `ui.state: recording`
   - Optional beep sound indicates recording has started
   - Speak your message
   - Press ENTER again to stop recording OR wait for silence detection (VAD)

3. **Processing (COMMIT → WAIT_REPLY)**
   - System displays: `ui.state: processing`
   - Your audio is sent to the server for transcription and processing

4. **Response Playback (SPEAKING)**
   - System displays: `ui.state: speaking`
   - Assistant's response is played back

5. **Return to Ready (CLOSING → IDLE)**
   - System automatically returns to `ui.state: idle`
   - Ready for next interaction - press ENTER to start again

## State Machine Flow

```
IDLE → [ENTER] → ARMING → [ding] → RECORDING → [ENTER or VAD] → COMMIT
  ↑                                                                 ↓
  ↑                                                           WAIT_REPLY
  ↑                                                                 ↓
  ↑                                                           SPEAKING
  ↑                                                                 ↓
  └──────────────────────────────────────────────────────── CLOSING
```

## Configuration

PTT mode can be configured in your `config.toml`:

```toml
[service]
beep = true  # Enable/disable beep sound on recording start
hotword_engine = "ptt"  # Force PTT mode

[ptt]
enabled = true

[vad]
enabled = false  # Disable VAD for manual control, or enable for auto-stop on silence
```

## Examples

### Stream mode with beep
```bash
./voice ptt --mode stream --service beep=true
```

### File mode without beep
```bash
./voice ptt --mode file --service beep=false
```

### Override language
```bash
./voice ptt --mode stream --lang en
```

## Troubleshooting

### ALSA devices busy
If you get ALSA errors, use `--force` to kill blocking processes:
```bash
./voice ptt --mode stream --force
```

### No response after ENTER
- Check that you're using the correct mode (`--mode stream` requires API keys)
- Verify your config.toml has proper API credentials
- Check logs for error messages

### Recording not stopping
- Press ENTER again to manually stop
- Or enable VAD with `--vad enabled=true` for auto-stop on silence

## Technical Details

The PTT keyboard handler in `apps/voice/stream/svc_streaming.py`:
- Runs as an async task (`_keyboard_ptt_loop`)
- Uses non-blocking stdin polling with `select.select()`
- Sends PTT state machine events (`START`, `DING_COMPLETE`, `COMMIT_AUDIO`)
- Automatically transitions back to IDLE after each interaction

See `apps/voice/stream/state.py` for the full PTT state machine implementation.

---

## Deprecated Imports (for developers)

**⚠️  If you're working with the codebase:**

The PTT functionality has been refactored. Use the following imports:

- **PTT State Machine**: `from apps.voice.stream.state import PTTStateMachine`
- **Streaming Service**: `from apps.voice.stream.svc_streaming import StreamingVoiceService`
- **CLI Entry Points**: `from apps.voice.svc_stream_runner import run_ptt_stream`

**Removed/deprecated modules:**
- `apps.voice.state.StreamingVoicePTTMixin` → Use `PTTStateMachine` from `apps.voice.stream.state`
- `apps.voice.ptt_state` → Use `PTTStateMachine` from `apps.voice.stream.state`
- `apps.voice.svc_stream` → Use `apps.voice.stream.svc_streaming` or `apps.voice.svc_stream_runner`

See [docs_pl/apps/voice.md](apps/voice.md#deprecated--legacy-files) for complete migration guide.
