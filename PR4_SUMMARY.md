# PR-4: Docs & Guards - Summary

## Overview

This PR adds documentation deprecation sections and quality guard tools to prevent regression of the voice module refactoring completed in PR-1 through PR-3.

## Changes Made

### 1. Quality Guard Tools

**`tools/check_file_length.py`** (116 lines)
- Enforces 600-line limit on Python files in `apps/voice`
- Ignores test files (`test_*.py`, `*_test.py`)
- Tracks known exceptions (pre-existing files from incomplete PR-2):
  - `apps/voice/stream/service.py` (704 lines)
  - `apps/voice/service_impl.py` (705 lines)
  - `apps/voice/playback.py` (617 lines)
- Exit codes:
  - 0: All files pass
  - 1: New files exceed limit
  - 2: Known exceptions have regressed (grown larger)

**`tools/check_legacy_imports.py`** (200 lines)
- Blocks imports of removed/deprecated modules
- Hard blocks (exit code 1):
  - `apps/voice/ws_transport.py` (removed in PR-1)
  - `apps/voice/stream_transport.py` (removed in PR-1)
  - `apps/voice/cli_new.py` (removed in PR-1)
  - `apps/voice/svc_stream.py` (removed in PR-3)
  - `apps/voice/state.py` (removed in PR-3)
  - `apps/voice/ptt_state.py` (removed in PR-3)
  - `StreamingVoiceTransportMixin` (removed in PR-3)
  - `StreamingVoicePTTMixin` (removed in PR-3)
- Warnings only (exit code 0):
  - `apps/voice/audio/*` (pending migration)

### 2. Documentation Updates

**`docs/modules/voice.md`**
- Added "Deprecated / Legacy Files" section at end
- Documents all removed files from PR-1 and PR-3
- Provides migration guide for developers
- Notes `apps/voice/audio/*` as pending migration

**`docs/PTT_USAGE.md`**
- Added "Deprecated Imports (for developers)" section
- Documents correct imports for PTT functionality
- Links to main voice.md deprecation guide

**`docs/config/voice.md`**
- Added "Deprecated Configuration Files" section
- Notes that configuration keys remain unchanged
- Clarifies refactoring is internal only (no user action required)

### 3. CI/Pre-commit Integration

**`.pre-commit-config.yaml`**
- Added local hooks for quality guards:
  - `check-file-length`: Runs `tools/check_file_length.py`
  - `check-legacy-imports`: Runs `tools/check_legacy_imports.py`
- Both hooks run on every commit (`always_run: true`)
- Will block commits with new violations

## Verification

### Quality Guards Working

```bash
# File length check (passes with known exceptions)
$ python3 tools/check_file_length.py
✅ All files under 600 lines (checked 48 files, 3 known exceptions)

# Legacy imports check (1 warning for audio/*, 0 errors)
$ python3 tools/check_legacy_imports.py
⚠️  Deprecated imports found (audio/* directory):
  tests/test_voice_audio_utils.py:16
    from apps.voice.audio import alsa, wavutil
    → apps/voice/audio/* (deprecated, pending migration to top-level)
✅ No hard-blocked legacy imports (but 1 audio/* import(s) should be migrated)
```

### Code Quality

- ✅ All new files pass `ruff check --fix`
- ✅ All new files pass `ruff format`
- ✅ Scripts are executable and work correctly

## Pre-existing Issues (Not Fixed in PR-4)

### Files Still Exceeding 600 Lines

According to the issue, PR-2 should have split these files. They remain oversized:
- `apps/voice/stream/service.py`: 704 lines (target: <600)
- `apps/voice/service_impl.py`: 705 lines (target: <600)
- `apps/voice/playback.py`: 617 lines (target: <600)

**Note**: PR-4 adds these as "known exceptions" to the file length guard, which:
- Allows them to exist (no CI failure)
- Prevents them from growing larger (regression detection)
- Blocks NEW files from exceeding 600 lines

These should be addressed in a follow-up PR to complete PR-2 objectives.

### Audio Directory Not Migrated

The `apps/voice/audio/*` directory still exists:
- `apps/voice/__init__.py` imports `ALSAError` from it
- `tests/test_voice_audio_utils.py` imports `alsa` and `wavutil` from it

**Note**: PR-1 noted this as "deferred to later PR". PR-4 adds it to the deprecation documentation and warns (but doesn't block) imports of it.

## Acceptance Criteria (from Issue)

- ✅ **Docs: one source of truth**
  - Updated `docs/modules/voice.md` with deprecation section
  - Updated `docs/config/voice.md` with note about internal changes
  - Updated `docs/PTT_USAGE.md` with developer migration guide
  - No mentions of `audio/*`, `ws_transport.py`, `stream_transport.py` as current/recommended

- ✅ **CI/Pre-commit guards**
  - `tools/check_file_length.py` created and working
  - `tools/check_legacy_imports.py` created and working
  - Both added to `.pre-commit-config.yaml`
  - Guards will fail CI on new violations

## Impact

### For Users
- **No breaking changes** - All configuration remains the same
- Documentation now clearly marks deprecated modules

### For Developers
- **Cannot reintroduce legacy patterns** - Pre-commit hooks block removed imports
- **Cannot create large monolithic files** - 600-line limit enforced for new files
- **Clear migration guide** - Documentation shows old → new import paths
- **Known exceptions tracked** - Pre-existing oversized files monitored for regression

## Next Steps (Future PRs)

1. **Complete PR-2 objectives**:
   - Split `stream/service.py` (704 → <600 lines)
   - Split `service_impl.py` (705 → <600 lines)
   - Split `playback.py` (617 → <600 lines)
   - Update `KNOWN_EXCEPTIONS` in `check_file_length.py` after splits

2. **Migrate audio/* directory**:
   - Move `ALSAError` to `apps/voice/errors.py`
   - Integrate `alsa.py` and `wavutil.py` into appropriate top-level modules
   - Update imports in `__init__.py` and tests
   - Remove `apps/voice/audio/*` directory
   - Remove from deprecation warnings in `check_legacy_imports.py`

## Files Changed

- **Added**: `tools/check_file_length.py` (116 lines)
- **Added**: `tools/check_legacy_imports.py` (200 lines)
- **Modified**: `docs/modules/voice.md` (+35 lines: deprecation section)
- **Modified**: `docs/PTT_USAGE.md` (+16 lines: developer note)
- **Modified**: `docs/config/voice.md` (+11 lines: deprecation note)
- **Modified**: `.pre-commit-config.yaml` (+13 lines: guard hooks)

**Total**: +375 lines (new guards + documentation)
