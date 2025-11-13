# Migracja do nowej konwencji nazewnictwa plików konfiguracyjnych Voice

**Data:** 2025-01  
**Wersja:** 1.0  
**Status:** Aktywna refaktoryzacja

## Cel

Wprowadzenie jednoznacznej i intuicyjnej struktury nazewnictwa dla plików konfiguracyjnych usług głosowych. Poprzednia konwencja stała się niejednoznaczna po dodaniu wsparcia dla Google Gemini.

## Nowa konwencja nazewnicza

```
voice_<provider>_<mode>.toml
```

Gdzie:
- **`<provider>`** — dostawca usług AI: `openai`, `gemini`
- **`<mode>`** — tryb komunikacji: `file` (REST API), `streaming` (WebSocket)

## Zmiana nazw plików

| Stara nazwa | Nowa nazwa | Opis |
|-------------|------------|------|
| `voice_file.toml` | `voice_openai_file.toml` | OpenAI w trybie plikowym |
| `voice_streaming.toml` | `voice_openai_streaming.toml` | OpenAI w trybie strumieniowym |
| `voice_streaming_fallback.toml` | `voice_openai_streaming_fallback.toml` | OpenAI streaming z fallbackiem |
| `voice_gemini_file.toml` | `voice_gemini_file.toml` | **Bez zmian** (już zgodne) |

## Wpływ na istniejący kod

### ✅ Bez zmian dla użytkowników

- **Domyślne zachowanie:** Wszystkie polecenia `make` działają bez zmian
- **Funkcjonalność:** Żadna funkcjonalność nie została utracona
- **Konfiguracje:** Zawartość plików `.toml` pozostaje identyczna

### ⚠️ Wymagane zmiany dla skryptów niestandardowych

Jeśli masz własne skrypty lub komendy odwołujące się do starych nazw:

```bash
# Stare (nie działa):
python -m apps.voice.cli --config ./config/voice_file.toml ptt

# Nowe (poprawne):
python -m apps.voice.cli --config ./config/voice_openai_file.toml ptt
```

### Makefile

Wszystkie targety `make` zostały zaktualizowane automatycznie:

```bash
# Te polecenia działają bez zmian:
make voice-file-listen       # używa voice_openai_file.toml
make voice-file-ptt           # używa voice_openai_file.toml
make voice-stream-listen      # używa voice_openai_streaming.toml
make config-edit-file         # edytuje voice_openai_file.toml
make config-edit-stream       # edytuje voice_openai_streaming.toml
```

## Migracja konfiguracji lokalnych

### Jeśli skopiowałeś pliki konfiguracyjne do `config/local/`

1. **Zmień nazwy plików:**
   ```bash
   cd config/local/
   mv voice_file.toml voice_openai_file.toml
   mv voice_streaming.toml voice_openai_streaming.toml
   ```

2. **Zaktualizuj własne skrypty:**
   ```bash
   # Znajdź wszystkie odniesienia:
   grep -r "voice_file.toml" .
   grep -r "voice_streaming.toml" .
   
   # Zastąp ręcznie lub używając sed:
   sed -i 's/voice_file\.toml/voice_openai_file.toml/g' twoj_skrypt.sh
   ```

## Nowe możliwości

### Łatwe przełączanie między providerami

```bash
# OpenAI
python -m apps.voice.cli --config ./config/voice_openai_file.toml ptt

# Google Gemini
python -m apps.voice.cli --config ./config/voice_gemini_file.toml ptt
```

### Klarowna struktura katalogów

```
config/
├── voice_openai_file.toml              # OpenAI REST
├── voice_openai_streaming.toml         # OpenAI WebSocket
├── voice_openai_streaming_fallback.toml
├── voice_gemini_file.toml              # Gemini REST
└── voice_gemini_example.toml           # Przykład
```

## Testowanie

Wszystkie testy zostały zaktualizowane i przechodzą pomyślnie:

```bash
# Uruchom testy konfiguracji:
python3 -m pytest tests/config/test_config_loader.py -v

# Demo walidacji:
PYTHONPATH=. python3 scripts/demo/config_validation.py
```

## Dokumentacja

Zaktualizowana dokumentacja:

- **docs/config/voice.md** — główna dokumentacja konfiguracji voice
- **docs/integracja-google-gemini.md** — integracja Gemini
- **docs/CONFIG_POLICY.md** — polityka konfiguracji
- **docs/config/README.md** — przegląd plików konfiguracyjnych

## FAQ

### Q: Czy muszę aktualizować swoje pliki konfiguracyjne?

**A:** Nie, jeśli używasz poleceń `make`. Jeśli masz własne skrypty, zaktualizuj ścieżki do plików.

### Q: Co się stanie ze starymi plikami?

**A:** Zostały przemianowane za pomocą `git mv`, więc historia Git jest zachowana.

### Q: Czy mogę używać starych nazw?

**A:** Nie, stare nazwy nie istnieją już w repozytorium. Musisz użyć nowych nazw.

### Q: Jak utworzyć konfigurację dla innego providera?

**A:** Skopiuj przykładowy plik i dostosuj:

```bash
# Dla nowego providera "anthropic":
cp config/voice_openai_file.toml config/voice_anthropic_file.toml
# Edytuj plik i zmień [chat] backend = "anthropic"
```

### Q: Czy konwencja obowiązuje dla wszystkich plików konfiguracyjnych?

**A:** Obecnie tylko dla plików `voice_*.toml`. Inne pliki (np. `face.toml`) zachowują swoje nazwy.

## Checklist migracji

- [ ] Zaktualizuj własne skrypty używające starych nazw plików
- [ ] Zmień nazwy lokalnych kopii konfiguracji w `config/local/`
- [ ] Zaktualizuj dokumentację projektową (jeśli dotyczy)
- [ ] Poinformuj zespół o zmianach
- [ ] Przetestuj polecenia `make voice-*`
- [ ] Zweryfikuj własne skrypty CI/CD

## Wsparcie

W przypadku problemów:

1. Sprawdź [docs/config/voice.md](config/voice.md)
2. Uruchom `make voice-diag` dla diagnostyki
3. Zgłoś issue na GitHub z tagiem `config`

---

**Ostatnia aktualizacja:** 2025-01  
**Related PR:** #[numer PR]  
**Related docs:** [voice.md](config/voice.md), [integracja-google-gemini.md](integracja-google-gemini.md)
