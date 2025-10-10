# Voice Module Refactoring Summary (PR#1–PR#5)

## Overview

This document summarizes the complete refactoring of the `apps/voice` module conducted in PR#1 through PR#5 (2024 Q4). The refactoring focused on eliminating code duplication, improving modularity, and establishing clear separation between file-based and streaming voice processing modes.

## Goals

1. **Eliminate duplicates** — Remove ~1600 lines of duplicated WebSocket transport, state machine, and service code
2. **Modular architecture** — Clear separation: file mode vs. streaming mode
3. **Testability** — Remove test-only shims, migrate to production code
4. **Documentation** — Single source of truth for architecture and migration
5. **Quality guards** — Prevent regression (legacy imports, file length limits)

## Timeline and PRs

### PR#1: Clean & Freeze (Foundation)
**Focus**: Remove obvious duplicates, establish baseline

**Files removed:**
- `apps/voice/ws_transport.py` (289 lines) — duplicate WebSocket transport
- `apps/voice/stream_transport.py` (120 lines) — duplicate, unused

**Files retained:**
- `apps/voice/audio/*` — deferred to later PR (active usage found)

**Result**: Clean baseline, 409 lines removed

---

### PR#2: CLI Unification
**Focus**: Consolidate CLI references, remove phantom modules

**Changes:**
- Updated Makefile (6 targets): `cli_new` → `cli`
- Updated `tools/check_legacy_imports.py` (removed `cli_new` patterns)
- Updated documentation (3 files)

**Files changed**: 6 files, 17 lines modified

**Result**: Single CLI module (`apps.voice.cli`), no broken references

---

### PR#3: Tests Migration & Shim Removal
**Focus**: Remove compatibility shims, migrate tests to production code

**Files removed:**
- `apps/voice/svc_stream.py` (104 lines) — re-export shim
- `apps/voice/state.py` (364 lines) — `StreamingVoicePTTMixin` (replaced by `PTTStateMachine`)
- `apps/voice/ptt_state.py` (324 lines) — duplicate PTT state
- Mixins from `transport.py` (59 lines) — `StreamingVoiceTransportMixin`

**Files created:**
- `apps/voice/svc_stream_runner.py` (84 lines) — CLI wrappers for streaming mode

**Tests migrated**: 9 test files updated to use production modules

**Result**: 857 lines removed, 84 lines added (net: -773 lines)

---

### PR#4: WebSocket Transport Consolidation
**Focus**: Remove last transport duplicate

**Files removed:**
- `apps/voice/transport.py` (319 lines) — duplicate of `stream/transport.py`

**Files updated:**
- `tools/check_legacy_imports.py` (+4 lines) — block `transport.py` imports
- `docs/modules/voice.md` (+3 lines) — migration guide
- `docs/QUALITY_GUARDS.md` (+4 lines) — documentation

**Result**: 319 lines removed, single transport implementation

---

### PR#5: Documentation (This PR)
**Focus**: Consolidate architecture documentation

**Files updated:**
- `ARCHITECTURE.md` — new section "Moduł Voice — Architektura szczegółowa" (150+ lines)
- `docs/modules/voice.md` — new section "Architektura modułu" (200+ lines)
- `docs/modules/voice-refactoring-summary.md` — this document (new)

**Content added:**
- Component descriptions (svc_core, svc_file, stream/*)
- Data flow diagrams (file mode vs. streaming mode)
- PR history and migration guides
- Summary tables

**Result**: Comprehensive documentation of new architecture

---

## Net Impact

### Code Changes
- **Lines removed**: ~1600 (duplicates, shims, legacy code)
- **Lines added**: ~600 (new modules, documentation)
- **Net reduction**: -1000 lines (~15% of voice module)

### Files
- **Removed**: 6 files (ws_transport, stream_transport, svc_stream, state, ptt_state, transport)
- **Created**: 2 files (svc_stream_runner, voice-refactoring-summary)
- **Modified**: 50+ files (tests, documentation, quality guards)

### Quality
- **Tests**: 100% migration from shims to production code
- **Ruff**: All files pass linting (≤120 chars/line)
- **Guards**: Pre-commit hooks prevent legacy import regression

## Architecture After Refactoring

### File Structure

```
apps/voice/
├── svc_core.py              # Mode selection (file vs. stream)
├── svc_file.py              # File mode service
├── svc_file_pipeline.py     # File mode pipeline (ASR→Chat→TTS)
├── svc_stream_runner.py     # Stream mode CLI wrappers
│
├── stream/                  # Streaming mode package
│   ├── service.py           # StreamingVoiceService (main class)
│   ├── transport.py         # WebSocket transport (single impl)
│   ├── state.py             # PTTStateMachine
│   ├── handlers.py          # StreamHandlersMixin
│   └── playout.py           # StreamPlayoutMixin
│
├── audio/                   # Low-level audio (pending migration)
│   ├── capture.py
│   ├── playback.py
│   ├── alsa.py
│   └── wavutil.py
│
├── cli.py                   # CLI interface
├── cli_commands.py          # CLI command implementations
├── web.py                   # HTTP API (Flask)
├── main.py                  # systemd entry point
│
└── [asr.py, chat.py, tts.py, vad.py, kws.py, ...]  # Backend integrations
```

### Mode Selection Logic

```python
# apps/voice/svc_core.py
def run_listen(cfg, args):
    if _is_realtime_mode(cfg):
        from .svc_stream_runner import run_listen_stream
        return run_listen_stream(cfg, args)
    else:
        from .svc_file import run_listen_file
        return run_listen_file(cfg, args)
```

Realtime mode requires: `transport = "realtime"` in **all** of `[asr]`, `[chat]`, `[tts]` sections.

### Data Flow

**File Mode:**
```
Hotword → Capture (VAD) → ASR → Chat → TTS → Playback → Loop
```

**Streaming Mode:**
```
PTT → WebSocket Connect → Audio Duplex:
  TX: Capture chunks → audio.append
  RX: partial ASR → Chat stream → TTS chunks → Playback
Barge-in → Cancel TTS, new turn
```

## Migration Guide

### For Developers

**Streaming service imports:**
```python
# ❌ OLD (removed)
from apps.voice.svc_stream import StreamingVoiceService
from apps.voice.transport import WebSocketTransport
from apps.voice.state import StreamingVoicePTTMixin

# ✅ NEW (correct)
from apps.voice.stream.service import StreamingVoiceService
from apps.voice.stream.transport import WebSocketTransport
from apps.voice.stream.state import PTTStateMachine
```

**CLI entry points:**
```python
# ✅ Use high-level API (recommended)
from apps.voice.svc_core import run_listen, run_once, run_ptt

# ✅ Or mode-specific wrappers
from apps.voice.svc_stream_runner import run_listen_stream
from apps.voice.svc_file import run_listen_file
```

### For Tests

All tests have been migrated to use production modules. No test-only shims remain.

**Example (PTT state):**
```python
# ❌ OLD (removed)
def test_ptt_mixin():
    class TestService(StreamingVoicePTTMixin):
        pass
    # ...

# ✅ NEW (correct)
from apps.voice.stream.state import PTTStateMachine, PTTEvent

def test_ptt_state():
    ptt = PTTStateMachine(logger)
    ptt.handle_event(PTTEvent.PTT_START)
    # ...
```

## Quality Guards

### Legacy Imports Check

**Tool**: `tools/check_legacy_imports.py`

**Blocks** (exit code 1):
- `apps/voice/ws_transport`
- `apps/voice/stream_transport`
- `apps/voice/svc_stream`
- `apps/voice/state`
- `apps/voice/ptt_state`
- `apps/voice/transport`

**Warns** (exit code 0):
- `apps/voice/audio/*` (pending migration)

**Usage:**
```bash
python tools/check_legacy_imports.py
# Runs automatically in pre-commit hook
```

### File Length Check

**Tool**: `tools/check_file_length.py`

**Enforces**: 600-line limit on new files in `apps/voice`

**Known exceptions** (pre-existing):
- `stream/service.py` (704 lines)
- `playback.py` (617 lines)

**Usage:**
```bash
python tools/check_file_length.py
# Runs automatically in pre-commit hook
```

## Lessons Learned

1. **Shims are technical debt** — Remove them as soon as tests can be migrated
2. **Documentation is code** — Keep architecture docs in sync with refactoring
3. **Quality guards prevent regression** — Automated checks catch accidental re-introduction of legacy patterns
4. **Incremental PRs** — Smaller PRs (#1-#5) easier to review than one mega-PR
5. **Test migration is work** — 9 test files required updates, but result is cleaner codebase

## Future Work

1. **Audio module migration** — Integrate `audio/*` into top-level modules or keep as specialized subpackage
2. **File splitting** — Reduce `stream/service.py` from 700+ to <600 lines (split into smaller mixins)
3. **Performance tuning** — Optimize jitter buffer, barge-in latency
4. **Additional backends** — Add support for other realtime providers (Azure, Anthropic, etc.)

## References

- **Main architecture**: `ARCHITECTURE.md`
- **Voice module docs**: `docs/modules/voice.md`
- **PR summaries**: `PR1_CHANGES.md`, `PR2_SUMMARY.md`, `PR3_SUMMARY.md`, `PR4_SUMMARY.md`
- **Quality guards**: `docs/QUALITY_GUARDS.md`
- **Code**: `apps/voice/` (175 files, ~15k LOC after refactoring)

---

**Status**: ✅ PR#1–PR#5 complete (2024 Q4)  
**Impact**: -1000 LOC, +comprehensive docs, +quality guards  
**Result**: Modular, testable, documented voice architecture
