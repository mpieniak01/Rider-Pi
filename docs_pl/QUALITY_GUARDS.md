# Rider-Pi Quality Guards - Usage Guide

## Overview

Two guards check Python file size across Rider-Pi and deprecated voice imports:

1. **`scripts/dev_check-file-length.py`** - Shared 600-line warning / 800-line hard limit
2. **`scripts/dev_check-legacy-imports.py`** - Blocks removed/deprecated imports

## Running Manually

```bash
# Check file length violations
python3 scripts/dev_check-file-length.py

# Check legacy imports
python3 scripts/dev_check-legacy-imports.py

# Run both
python3 scripts/dev_check-file-length.py && python3 scripts/dev_check-legacy-imports.py
```

## Pre-commit Integration

Lint runs on commit; file length and legacy imports run on pre-push/manual stages.

### Local environment

Use the repository's configured pre-commit installation and WSL virtualenv.
These checks require no robot runtime packages or global package installation.

### Run manually on all files

```bash
python -m pre_commit run check-file-length --hook-stage pre-push --from-ref origin/main --to-ref HEAD
python -m pre_commit run check-legacy-imports --hook-stage pre-push --from-ref origin/main --to-ref HEAD
```

### Skip guards (emergency only)

```bash
git commit --no-verify -m "..."
```

**Warning**: Only use `--no-verify` in emergencies. The guards are there to protect code quality.

## Limit długości plików

Jedna polityka w `scripts/dev_check-file-length.py` jest używana przez lokalny
hook pre-push oraz GitHub Quality Guard. Liczymy fizyczne linie, również
komentarze i puste wiersze, w zmienionych plikach Python, także testach i skryptach.

| Liczba linii | Wynik |
| --- | --- |
| 0–600 | Kontrola przechodzi |
| 601–800 | Ostrzeżenie; ocena spójności, bez obowiązkowego podziału |
| Powyżej 800 | Błąd; bramka blokuje zmianę |

Sprawdzamy zmienione pliki; niezmienione pliki historyczne nie blokują innego PR-u.
Nie ma wyjątków bez limitu. Dawna etykieta `allow-oversize` nie omija twardej bramki.

```bash
# Zmiany gałęzi względem main
python3 scripts/dev_check-file-length.py
# Rewizje przekazane przez CI
python3 scripts/dev_check-file-length.py --base BASE_SHA --head HEAD_SHA
# Jawne pliki, przekazywane również przez hook
python3 scripts/dev_check-file-length.py apps/motion/executor.py
# Lokalna bramka dla gałęzi
python -m pre_commit run check-file-length --hook-stage pre-push --from-ref origin/main --to-ref HEAD
```

Kod wyjścia 0 oznacza przejście kontroli, również przy ostrzeżeniach. Kod 1 oznacza
przekroczenie 800 linii albo brak możliwości odczytu pliku lub różnic Git.
`SOFT_LIMIT` i `HARD_LIMIT` we wspólnym skrypcie są jedynymi definicjami progów.
Hook egzekwuje regułę lokalnie bez dodatkowej zmiennej środowiskowej. CI wyświetla
adnotacje ostrzeżenia/błędu. Podział powinien wynikać ze spójnych odpowiedzialności;
długość pliku jest wskazówką utrzymania kodu, nie pomiarem CPU ani pamięci.

## Legacy Imports Guard

### What it blocks (exit code 1)

Files removed in PR-1:
- `apps/voice/ws_transport.py`
- `apps/voice/stream_transport.py`

Files removed in PR-3:
- `apps/voice/svc_stream.py`
- `apps/voice/state.py`
- `apps/voice/ptt_state.py`

Files removed in PR-4:
- `apps/voice/transport.py`

Mixins removed in PR-3:
- `StreamingVoiceTransportMixin`
- `StreamingVoicePTTMixin`

### What it warns about (exit code 0)

- `apps/voice/audio/*` directory (pending migration)

### Migration Guide

| Old Import | New Import |
|------------|-----------|
| `from apps.voice.svc_stream import StreamingVoiceService` | `from apps.voice.stream.svc_streaming import StreamingVoiceService` |
| `from apps.voice.state import StreamingVoicePTTMixin` | `from apps.voice.stream.state import PTTStateMachine` |
| `from apps.voice.transport import WebSocketTransport` | `from apps.voice.stream.transport import WebSocketTransport` |
| `from apps.voice.ws_transport import ...` | `from apps.voice.stream.transport import ...` |
| `from apps.voice.audio import alsa` | (Pending migration to top-level) |

See [docs/apps/voice.md](apps/voice.md#deprecated--legacy-files) for full migration guide.

## Troubleshooting

### Guard fails with "legacy import detected"

1. Check the error message for the blocked import
2. Consult the migration guide above
3. Update imports to use refactored modules
4. Re-run the guard to verify fix

### Guard fails with "file exceeds 800 lines"

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

Quality Guard invokes the shared size checker with the PR base/head revisions. The legacy-import hook remains separate. PRs fail if:
- Changed Python files exceed 800 lines
- Legacy imports are detected

## Questions?

See:
- [Guide](apps/voice.md) - Complete PR#1–PR#5 refactoring summary
- [Guide](apps/voice.md) - Voice module architecture
- [ARCHITECTURE.md](ARCHITECTURE.md) - Overall system architecture
- [Guide](apps/voice.md) - PR-4 transport consolidation details

