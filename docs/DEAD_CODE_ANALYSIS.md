# Dead Code Analysis Report - Rider-Pi Repository

Generated: 2025-10-11

## Summary

This report identifies potential dead code files in the Rider-Pi repository beyond the voice module refactoring.

## Methodology

1. Search for Python files not imported by any other module
2. Exclude test files, scripts, and main entry points
3. Focus on apps/ and services/ directories
4. Verify by checking git grep for imports

## Files Removed in This PR

### apps/voice/ - Dead Code (6 files)
- ✅ `apps/voice/audio/wavutil.py` - WAV utilities (only used in tests)
- ✅ `apps/voice/audio_rx_tts.py` - Audio receiver module (only used in tests)
- ✅ `apps/voice/audio_tx.py` - Audio transmitter module (only used in tests)
- ✅ `apps/voice/ding.py` - Ding sound generation (functionality moved to playback.py)
- ✅ `apps/voice/svc_file_pipeline.py` - Experimental pipeline (never used)
- ✅ `apps/voice/voice_metrics.py` - Metrics tracking (only used in tests)

### apps/voice/ - Renamed (1 file)
- ✅ `apps/voice/stream/service.py` → `apps/voice/stream/svc_streaming.py` (renamed for consistency)

## Other Potential Dead Code Candidates

### Checked and Active

The following modules were checked but found to be actively used:

#### apps/voice/
- `env_loader.py` - Used by service.py for environment loading
- `utils.py` - Used by various voice modules
- `web.py` - Used for web UI functionality
- `session_prefs.py` - Used for session preferences
- `rt_protocol.py` - Used by stream modules for realtime protocol
- `stream_chunks.py` - Used by streaming modules

#### apps/ui/
- All modules in apps/ui/ appear to be in active use
- face/ submodules are used by the face controller

#### apps/vision/
- All detector modules are in active use

### Previously Moved to _todelete/

The following files were already identified and moved to _todelete/ in previous refactoring:
- `apps/voice/_todelete/main.py` - Compatibility stub
- `apps/ui/face/driver/_todelete/spi.py` - Old SPI driver
- `apps/launcher/_todelete/main.py` - Duplicate of menu/main.py

## Recommendations

1. **Keep monitoring**: The guard scripts (dev_check-legacy-imports.py) should continue to prevent reintroduction of removed code
2. **Future migration**: apps/voice/audio/* directory should be migrated to top-level or kept as specialized package
3. **Documentation**: Update PR summaries to reflect these removals

## Verification Commands

To verify no broken imports:
```bash
# Check for legacy imports
python3 scripts/dev_check-legacy-imports.py

# Run tests
python3 -m pytest tests/test_voice*.py -v

# Check linting
ruff check apps/voice/ tests/ scripts/
```

## Notes

- All removed files were verified to have no production code dependencies
- Tests that relied on removed modules were also removed
- Documentation and guard scripts updated accordingly
- Code quality maintained: ruff checks pass, 86/87 voice tests pass (1 pre-existing failure)

## Analysis Details

### How Dead Code Was Identified

1. **Import Analysis**: Used `git grep` to search for import statements across the entire codebase
2. **Test-Only Usage**: Files only imported by test files were flagged as dead code
3. **Duplicate Functionality**: Files where functionality was moved elsewhere (e.g., ding.py → playback.py)
4. **Never Used**: Files with no imports at all (e.g., svc_file_pipeline.py)

### Impact Assessment

- **Code Reduction**: ~1,600 lines of code removed
- **Test Coverage**: Reduced by 3 test files (testing dead modules)
- **Documentation**: Updated 6 documentation files
- **Guard Scripts**: Enhanced to prevent reintroduction

### Files Kept Despite Low Usage

Some files with limited usage were kept because they serve important purposes:

- **env_loader.py**: Used at initialization for environment setup
- **rt_protocol.py**: Core protocol definitions for streaming
- **session_prefs.py**: Session state management
- **web.py**: Web UI functionality

These are considered "infrastructure" rather than dead code.
