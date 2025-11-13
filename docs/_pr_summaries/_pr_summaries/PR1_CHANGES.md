# PR-1: Clean & Freeze - Changes Summary

## Overview
This PR removes legacy/unused files from `apps/voice` as part of the refactoring plan to simplify the voice architecture.

## Files Removed

### 1. `apps/voice/ws_transport.py` (289 lines)
**Reason**: Duplicate/legacy WebSocket transport implementation. Functionality superseded by:
- `apps/voice/stream/transport.py` (modern implementation)
- `apps/voice/transport.py` (re-exports from stream/transport.py)

**Verification**: No imports found in codebase (`git grep` returned 0 results)

### 2. `apps/voice/stream_transport.py` (120 lines)
**Reason**: Duplicate/legacy transport implementation extracted during previous refactoring but never used. Functionality is in `apps/voice/stream/transport.py`.

**Verification**: No imports found in codebase

### 3. CLI files consolidated
**Reason**: The new CLI implementation was already integrated into `apps/voice/cli.py` and `apps/voice/cli_commands.py` as part of the modular architecture.

**Result**: References to `cli_new` removed in PR-2 (CLI Unification).

## Files Modified

### `apps/voice/transport.py`
**Change**: Enhanced `StreamingVoiceTransportMixin` stub to support legacy tests.

**Details**:
- Added `send()` method with rate-limited logging for test compatibility
- Implements environment-based logging controls (`VOICE_WS_LOG`, `VOICE_WS_APPEND_SAMPLE_EVERY`)
- Defensive initialization to work with test classes that don't call `__init__()`
- Maintains backward compatibility for `tests/test_transport_logging.py`

**Rationale**: The issue requires maintaining test compatibility in PR-1. The mixin is marked as deprecated but needs minimal functionality for tests to pass.

## Files Retained (Deferred to Later PR)

### `apps/voice/audio/*` directory
**Status**: KEPT (contradicts initial issue description)

**Reason**: Active usage found in codebase:
- `apps/voice/__init__.py` imports `ALSAError` from `audio/errors.py`
- `apps/voice/cli.py` and `apps/voice/cli_commands.py` import from `audio/alsa.py` and `audio/wavutil.py`
- `tests/test_voice_audio_utils.py` imports from `audio/alsa.py` and `audio/wavutil.py`
- Contains unique functionality (`alsa.py`, `wavutil.py`) not duplicated elsewhere

**Next Steps**: Migration requires:
1. First migrate `ALSAError` usage to `apps/voice/errors.py`
2. Integrate `alsa.py` and `wavutil.py` functionality into top-level modules
3. Update test imports
4. Then remove `audio/*` directory (likely in PR-3)

## Test Results

All voice-related tests pass:
```
tests/test_voice_svc_stream_proxy.py ....                   [PASS]
tests/test_transport_logging.py .                           [PASS]
tests/test_voice_audio_utils.py ................            [PASS]
======================== 21 passed, 1 warning ==============
```

## Code Quality

- ✅ `ruff check` passes with no errors
- ✅ `ruff format` applied to modified files
- ✅ No imports reference removed files
- ✅ All shims functioning correctly

## Architecture State

### Shims (Compatibility Layer)
1. **`apps/voice/svc_stream.py`**: Re-exports from `stream/service.py` ✅ Working
2. **`apps/voice/transport.py`**: Provides transport classes + legacy mixin ✅ Working

### Modern Implementation
- `apps/voice/stream/service.py` - Main streaming service (1243 lines, to be split in PR-2)
- `apps/voice/stream/transport.py` - WebSocket transport (316 lines)
- `apps/voice/stream/state.py` - State machine (259 lines)

### File Mode
- `apps/voice/service_impl.py` - File-based service (763 lines, to be split in PR-2)
- `apps/voice/svc_file.py` - File mode entry points
- `apps/voice/svc_file_pipeline.py` - Pipeline logic (275 lines)

## Notes for Next PR (PR-2)

PR-2 should focus on splitting large files:
1. `apps/voice/stream/service.py` (1243 lines) → 3 files
2. `apps/voice/service_impl.py` (763 lines) → 2-3 files  
3. `apps/voice/playback.py` (617 lines) → 2 files

Each resulting file should be <600 lines as per the issue requirements.
