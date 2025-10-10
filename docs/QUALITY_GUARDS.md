# Voice Module Quality Guards - Usage Guide

## Overview

Two quality guard tools prevent regression of the voice module refactoring:

1. **`tools/check_file_length.py`** - Enforces 600-line limit
2. **`tools/check_legacy_imports.py`** - Blocks removed/deprecated imports

## Running Manually

```bash
# Check file length violations
python3 tools/check_file_length.py

# Check legacy imports
python3 tools/check_legacy_imports.py

# Run both
python3 tools/check_file_length.py && python3 tools/check_legacy_imports.py
```

## Pre-commit Integration

The guards run automatically on every commit via pre-commit hooks.

### Install pre-commit (if not already installed)

```bash
pip install pre-commit
pre-commit install
```

### Run manually on all files

```bash
pre-commit run check-file-length --all-files
pre-commit run check-legacy-imports --all-files
```

### Skip guards (emergency only)

```bash
git commit --no-verify -m "..."
```

**Warning**: Only use `--no-verify` in emergencies. The guards are there to protect code quality.

## File Length Guard

### What it checks
- All Python files in `apps/voice/` (excluding test files)
- Maximum 600 lines per file

### Known Exceptions (pre-existing)
- `apps/voice/stream/service.py` (704 lines)
- `apps/voice/svc_file.py` (758 lines, consolidated from service_impl in PR#1, updated in PR#3)

These files are tracked from incomplete PR-2. The guard:
- ✅ Allows them to exist
- ❌ Blocks them from growing larger (regression detection)
- ❌ Blocks NEW files from exceeding 600 lines

### Exit Codes
- `0` - Pass (all files ≤600 or in known exceptions)
- `1` - Fail (new file exceeds 600)
- `2` - Regression (known exception grew larger)

### Adding a Known Exception

If justified (rare cases), edit `tools/check_file_length.py`:

```python
KNOWN_EXCEPTIONS = {
    "apps/voice/stream/service.py": 704,
    "apps/voice/svc_file.py": 758,
    # Add new exception only if absolutely necessary:
    # "apps/voice/some_file.py": 650,  # Reason: ...
}
```

**Justification required** in commit message for adding exceptions.

## Legacy Imports Guard

### What it blocks (exit code 1)

Files removed in PR-1:
- `apps/voice/ws_transport.py`
- `apps/voice/stream_transport.py`

Files removed in PR-3:
- `apps/voice/svc_stream.py`
- `apps/voice/state.py`
- `apps/voice/ptt_state.py`

Mixins removed in PR-3:
- `StreamingVoiceTransportMixin`
- `StreamingVoicePTTMixin`

### What it warns about (exit code 0)

- `apps/voice/audio/*` directory (pending migration)

### Migration Guide

| Old Import | New Import |
|------------|-----------|
| `from apps.voice.svc_stream import StreamingVoiceService` | `from apps.voice.stream.service import StreamingVoiceService` |
| `from apps.voice.state import StreamingVoicePTTMixin` | `from apps.voice.stream.state import PTTStateMachine` |
| `from apps.voice.ws_transport import ...` | `from apps.voice.stream.transport import ...` |
| `from apps.voice.audio import alsa` | (Pending migration to top-level) |

See [docs/modules/voice.md](../docs/modules/voice.md#deprecated--legacy-files) for full migration guide.

## Troubleshooting

### Guard fails with "legacy import detected"

1. Check the error message for the blocked import
2. Consult the migration guide above
3. Update imports to use refactored modules
4. Re-run the guard to verify fix

### Guard fails with "file exceeds 600 lines"

1. Split the file into smaller, focused modules
2. Follow the pattern from PR-2 (handlers, playout, etc.)
3. Update imports in dependent files
4. Verify tests still pass

### False positive

If a guard reports a false positive:
1. File an issue with details
2. Provide justification for exception
3. Update guard script if approved

## CI Integration

The guards run in CI via pre-commit hooks. PRs will fail if:
- New files exceed 600 lines
- Legacy imports are detected
- Known exceptions regress (grow larger)

## Questions?

See:
- [PR4_SUMMARY.md](../PR4_SUMMARY.md) - Full PR-4 details
- [docs/modules/voice.md](../docs/modules/voice.md) - Voice module architecture
- Issue comments for context on guard decisions
