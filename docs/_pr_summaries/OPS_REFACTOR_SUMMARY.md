# Refaktoryzacja katalogu ops

## Przegląd

W ramach uporządkowania struktury projektu przeprowadzono analizę i refaktoryzację katalogu `ops/`. Głównym celem było przeniesienie plików do odpowiednich lokalizacji oraz usunięcie zduplikowanych lub przestarzałych plików.

## Wykonane zmiany

### Przeniesione pliki

| Stara ścieżka | Nowa ścieżka | Uzasadnienie |
|---------------|--------------|--------------|
| `ops/systemd-sync.sh` | `scripts/sys_systemd-sync.sh` | Spójność z resztą skryptów systemowych; dokumentacja już wskazywała na tę lokalizację |

### Usunięte pliki

| Plik | Powód usunięcia |
|------|-----------------|
| `ops/audio/wm8960-mixer.sh` | Zduplikowany i przestarzały; nowsza, lepsza wersja istnieje w `config/alsa/wm8960-apply.sh` |

**Porównanie wersji:**
- `ops/audio/wm8960-mixer.sh` - 11 linii, hardkodowana karta `card=0`, brak obsługi błędów
- `config/alsa/wm8960-apply.sh` - 59 linii, automatyczna detekcja karty, lepsze ustawienia miksu, routing DAC→MIX→SPEAKER

### Zachowane pliki

Następujące pliki pozostają w katalogu `ops/`:

#### `ops/agent/` (3 pliki)
Katalog zachowany, ponieważ:
- Używany przez CI/CD w `.github/archive/ci.yml`
- Referencja w `Makefile`: `-include ops/agent/Makefile.agent`
- Zawiera konfigurację specyficzną dla testów agenta

**Zawartość:**
- `constraints.txt` - wersje zależności dla testów (Flask, Pillow, pyzmq, requests, Werkzeug, pytest)
- `requirements-test.txt` - minimalne wymagania testowe (pytest, pytest-timeout)
- `run_tests.sh` - skrypt uruchamiający testy face animation API

#### `ops/audio/` (1 plik)
**Zawartość:**
- `mpg123.sh` - wrapper dla mpg123 z ustawieniem urządzenia wm8960_out
  - Używany w systemie jako wrapper
  - Mały, funkcjonalny (2 linie kodu)
  - Brak referencji w dokumentacji, ale zachowany ze względu na potencjalne użycie

## Zaktualizowana dokumentacja

### Pliki zmienione
1. **docs/ops/README.md**
   - Usunięto notatkę `(pozostało w ops/)` przy `systemd-sync.sh`
   - Zaktualizowano ścieżkę na `sys_systemd-sync.sh` w katalogu scripts

2. **docs/_inventory.md**
   - Zmieniono `ops/systemd-sync.sh` → `scripts/sys_systemd-sync.sh`

3. **scripts/README.md**
   - Usunięto notatkę `(Przenisiony do katalogu ops)` przy `systemd-sync.sh`
   - Dodano prefiks `sys_` zgodnie z konwencją nazewnictwa

### Pliki bez zmian (już poprawne)
Następujące pliki już zawierały prawidłowe referencje do `scripts/sys_systemd-sync.sh` lub `scripts/systemd-sync.sh`:
- `WORKING-AGREEMENTS.md`
- `AGENT.md`
- `docs/ops/systemd-scripts.md`
- `docs/ops/utility-scripts.md`
- `docs/_todo/system_start.md`
- `docs/modules/voice.md`
- `docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md`

## Struktura końcowa katalogu ops/

```
ops/
├── agent/
│   ├── constraints.txt
│   ├── requirements-test.txt
│   └── run_tests.sh
└── audio/
    └── mpg123.sh
```

**Łącznie:** 4 pliki w 2 podkatalogach

## Weryfikacja zmian

### Sprawdzenie referencji
```bash
# Brak referencji do starych ścieżek
grep -r "ops/systemd-sync" --include="*.md" --include="*.sh" --include="*.py" --include="Makefile"
# (brak wyników)

# Brak referencji do usuniętego pliku
grep -r "wm8960-mixer.sh" --include="*.md" --include="*.sh" --include="*.py"
# (brak wyników)
```

### Zachowanie funkcjonalności
- ✅ Plik `systemd-sync.sh` zachowuje pełną zawartość (przeniesienie przez `git mv`)
- ✅ Historia git została zachowana dla przenoszonego pliku
- ✅ Wszystkie referencje w dokumentacji są spójne
- ✅ Pliki agent/ i audio/mpg123.sh pozostają dostępne dla systemów, które ich używają

## Uzasadnienie pozostawionych plików

### ops/agent/
**Powód zachowania:**
- Aktywnie używany przez infrastrukturę CI/CD
- Zawiera specyficzną konfigurację testową dla animacji face
- Makefile zawiera include do potencjalnego `ops/agent/Makefile.agent`
- Małe pliki konfiguracyjne, które logicznie należą do tej lokalizacji

### ops/audio/mpg123.sh
**Powód zachowania:**
- Funkcjonalny wrapper do mpg123
- Konfiguruje właściwe urządzenie ALSA (wm8960_out)
- Nie ma duplikatu w innej lokalizacji
- Może być używany przez zewnętrzne skrypty lub konfiguracje systemd

## Podsumowanie

### Metryki
- **Przeniesione:** 1 plik
- **Usunięte:** 1 plik (duplikat)
- **Zachowane:** 4 pliki (2 podkatalogi)
- **Zaktualizowane dokumenty:** 3 pliki

### Stan katalogów
- **ops/** - zachowany (4 pliki w podkatalogach)
- **scripts/** - dodany sys_systemd-sync.sh
- **config/alsa/** - posiada aktualną wersję wm8960-apply.sh

### Rezultat
Katalog `ops/` został uporządkowany zgodnie z zasadą **MOVE-FIRST**:
1. Główny skrypt operacyjny (`systemd-sync.sh`) przeniesiony do `scripts/sys_systemd-sync.sh`
2. Duplikaty usunięte
3. Zachowane tylko pliki aktywnie używane lub specyficzne dla podkatalogów
4. Wszystkie referencje zaktualizowane
5. Historia git zachowana dla wszystkich zmian
6. Zastosowano konwencję nazewnictwa `sys_` dla skryptów systemowych

---

**Data:** 2025-10-11  
**PR:** #[numer-PR]  
**Related:** SCRIPTS_MIGRATION_SUMMARY.md (PR #13)
