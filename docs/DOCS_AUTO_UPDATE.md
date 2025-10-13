# Automatyczna aktualizacja referencji w dokumentacji

## Przegląd

Ten dokument opisuje narzędzia automatycznej aktualizacji i walidacji referencji do plików i komend w dokumentacji Rider-Pi.

## Narzędzia

### `dev_update-docs-references.py`

Automatycznie aktualizuje referencje do plików i komend w plikach `.md` zgodnie z aktualną architekturą projektu.

**Funkcjonalność:**
- Ekstrakcja mapy migracji z `docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md`
- Dodawanie reguł repo-first (np. preferowanie `make lcd-on` zamiast `python3 ops/lcdctl.py on`)
- Skanowanie wszystkich plików `.md` w repozytorium
- Automatyczna podmiana starych ścieżek na nowe
- Weryfikacja, że nowe ścieżki faktycznie istnieją w repo
- Pomijanie kontekstów dokumentacyjnych (tabele migracji, historie zmian)
- Oznaczanie zdeprecjonowanych usług (np. `rider-dispatcher.service`)

**Użycie:**

```bash
# Tylko weryfikacja - sprawdź czy wszystkie mapowania wskazują na istniejące pliki
python3 scripts/dev_update-docs-references.py --verify-only

# Dry run - pokaż co zostałoby zmienione bez modyfikacji plików
python3 scripts/dev_update-docs-references.py --dry-run

# Wykonaj aktualizację
python3 scripts/dev_update-docs-references.py
```

**Przykład wyjścia:**

```
Building migration map...
Total mappings: 64

Scanning markdown files... (dry_run=False)
✓ Updated AGENT.md
✓ Updated docs/ops/systemd-scripts.md

Updated 2 file(s):

AGENT.md:
  Line 18: scripts/sys_systemd-sync.sh → scripts/systemd-sync.sh

docs/ops/systemd-scripts.md:
  Line 107: scripts/sys_systemd-sync.sh → scripts/systemd-sync.sh

Total changes: 2
```

### `dev_validate-docs-links.py`

Waliduje referencje i linki w dokumentacji, wykrywając:
- Nieistniejące pliki
- Przestarzałe ścieżki (`ops/*`, `tools/*`)
- Nieistniejące cele w Makefile
- Zepsute linki markdown

**Użycie:**

```bash
python3 scripts/dev_validate-docs-links.py
```

**Przykład wyjścia:**

```
Validating documentation references...

docs/PTT_USAGE.md:
  ❌ ERROR: File not found: modules/voice.md#deprecated--legacy-files

docs/modules/voice.md:
  ⚠️  WARNING: Makefile target not found: make voice-ptt

============================================================
Scanned 74 markdown files
Files with issues: 2
Total errors: 1
Total warnings: 1

❌ Validation FAILED - fix errors above
```

## Mapa migracji

Narzędzia budują mapę migracji z dwóch źródeł:

### 1. SCRIPTS_MIGRATION_SUMMARY.md

Tabele w tym pliku dokumentują przeniesienia plików:

```markdown
| Old Path | New Path |
|----------|----------|
| ops/lcdctl.py | scripts/sys_lcd-control.py |
| ops/boot_prepare.sh | scripts/sys_boot-prepare.sh |
```

### 2. Reguły repo-first

Dodatkowe reguły nadpisujące domyślne mapowania:

```python
# Preferuj make targets zamiast bezpośrednich wywołań
"python3 ops/lcdctl.py on" → "make lcd-on"
"python3 ops/lcdctl.py off" → "make lcd-off"

# Preferuj wrapper scripts
"ops/splash_device_info.py" → "scripts/sys_splash-info.py"

# Poprawki nazewnictwa
"scripts/sys_systemd-sync.sh" → "scripts/systemd-sync.sh"
```

## Inteligentne pomijanie kontekstów

Skrypty **nie aktualizują** referencji w następujących kontekstach:

1. **Pliki dokumentujące migracje:**
   - `docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md`
   - `docs/OPS_REMOVAL.md`

2. **Tabele markdown** pokazujące mapowania old→new:
   ```markdown
   | Old Path | New Path |
   |----------|----------|
   ```

3. **Linie ze strzałką** dokumentujące zmiany:
   ```markdown
   - ops/lcdctl.py → scripts/sys_lcd-control.py
   ```

4. **Konteksty legacy/deprecated:**
   - Linie zawierające "legacy", "deprecated", "removed in PR", "przestarzałe"

## Workflow aktualizacji dokumentacji

### Przed PR ze zmianami w scripts/

1. **Zaktualizuj SCRIPTS_MIGRATION_SUMMARY.md** z nowymi mapowaniami:
   ```markdown
   | ops/nowy_skrypt.py | scripts/sys_nowy-skrypt.py |
   ```

2. **Uruchom dry-run:**
   ```bash
   python3 scripts/dev_update-docs-references.py --dry-run
   ```

3. **Przejrzyj proponowane zmiany** i upewnij się, że są poprawne

4. **Wykonaj aktualizację:**
   ```bash
   python3 scripts/dev_update-docs-references.py
   ```

5. **Waliduj wyniki:**
   ```bash
   python3 scripts/dev_validate-docs-links.py
   ```

6. **Przejrzyj zmiany w git:**
   ```bash
   git diff docs/
   ```

### Po zmianach w strukturze

Jeśli dodajesz nowe reguły repo-first lub specjalne przypadki, edytuj:
- `scripts/dev_update-docs-references.py` → funkcja `add_repo_first_rules()`

## Weryfikacja przed merge

Przed zmergowaniem PR:

```bash
# 1. Sprawdź że wszystkie nowe ścieżki istnieją
python3 scripts/dev_update-docs-references.py --verify-only

# 2. Waliduj dokumentację
python3 scripts/dev_validate-docs-links.py

# 3. Sprawdź że nie ma referencji do legacy paths
grep -r "python3.*ops/\|python3.*tools/" docs/ --include="*.md" | \
  grep -v "SCRIPTS_MIGRATION\|OPS_REMOVAL\|→"
```

## Rozszerzanie narzędzi

### Dodawanie nowych wzorców migracji

W `dev_update-docs-references.py`, w funkcji `add_repo_first_rules()`:

```python
explicit_mappings = {
    'old/path.py': 'new/path.py',
    # ... więcej mapowań
}
```

### Dodawanie nowych komend do sprawdzenia

Dla komend typu `make target`:

```python
cmd_mappings = {
    r'python3 path/to/script\.py': 'make new-target',
}
```

### Dodawanie nowych kontekstów do pominięcia

W funkcji `should_skip_context()`:

```python
if 'nowy-marker' in line.lower():
    return True
```

## Historia zmian

- **2025-10-13**: Utworzenie narzędzi automatycznej aktualizacji
  - Pierwsza wersja `dev_update-docs-references.py`
  - Pierwsza wersja `dev_validate-docs-links.py`
  - Automatyczna aktualizacja referencji `sys_systemd-sync.sh` → `systemd-sync.sh`

## Zobacz także

- `docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md` – pełna mapa migracji scripts
- `docs/OPS_REMOVAL.md` – dokumentacja usunięcia katalogu ops/
- `scripts/README.md` – konwencje nazewnictwa w scripts/
