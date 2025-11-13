# Dokumentacja Rider-Pi Apps

> Centralny indeks dokumentacji projektu **Rider-Pi Apps** — oprogramowania rozszerzającego możliwości urządzenia Rider-Pi.

> **Uwaga**: Raporty historyczne w katalogu `docs/_pr_summaries/` mogą pozostać w języku angielskim, ponieważ stanowią zapis wcześniejszych wersji projektu.

## Dokumenty główne (katalog główny)

Najważniejsze dokumenty znajdują się w katalogu głównym projektu:

- [**README.md**](../README.md) — wprowadzenie do projektu, instalacja, szybki start
- [**PROJECT.md**](../PROJECT.md) — wizja projektu, cele biznesowe, roadmapa
- [**ARCHITECTURE.md**](../ARCHITECTURE.md) — architektura systemu, porty, przepływy danych
- [**ARCHITECTURE_DIAGRAM.md**](../ARCHITECTURE_DIAGRAM.md) — diagramy architektury
- [**AGENT.md**](../AGENT.md) — kontrakt dla asystenta kodu, zasady developerskie
- [**WORKING-AGREEMENTS.md**](../WORKING-AGREEMENTS.md) — ustalenia robocze zespołu
- [**CONFIG_POLICY.md**](CONFIG_POLICY.md) — **polityka konfiguracji i sekretów** (single source of truth)

---

## Dokumentacja modułów aplikacyjnych (`apps/*`)

Szczegółowa dokumentacja wszystkich modułów aplikacyjnych:

- [**apps/README.md**](apps/README.md) — **indeks modułów aplikacyjnych** (przegląd, zależności, uruchamianie)
- [**apps/chat.md**](apps/chat.md) — chat z OpenAI (audio.transcript → GPT → tts.speak)
- [**apps/nlu.md**](apps/nlu.md) — rozpoznawanie intencji ruchu z transkrypcji PL
- [**apps/launcher.md**](apps/launcher.md) — menu startowe na 4 przyciski
- [**apps/menu.md**](apps/menu.md) — menu nawigacyjne (duplikat launcher?)
- [**apps/motion.md**](apps/motion.md) — bridge ruchu (motion.cmd → XGO adapter)
- [**apps/safety.md**](apps/safety.md) — emergency stop (E-STOP)
- [**apps/demos.md**](apps/demos.md) — gotowe demonstracje ruchu
- [**apps/camera.md**](apps/camera.md) — preview kamery z detekcją twarzy na LCD
- [**apps/vision.md**](apps/vision.md) — detekcja obiektów (HOG, TFLite, ROI)
- [**apps/draw.md**](apps/draw.md) — prymitywy renderowania buźki
- [**apps/hw.md**](apps/hw.md) — sink LCD (framebuffer)
- [**apps/ui.md**](apps/ui.md) — przyciski, konfiguracja UI, kontroler buźki

### Dokumentacja modułów (legacy — `docs/modules/`)

- [**modules/voice.md**](modules/voice.md) — pełny stos głosowy (ASR, TTS, VAD, KWS, chat), tryby plikowy i strumieniowy
- [**modules/face.md**](modules/face.md) — API statycznego renderu buźki (endpointy HTTP, konfiguracja)
- [**modules/face-lcd.md**](modules/face-lcd.md) — renderowanie buźki na panelu LCD ILI9xx
- [**modules/face-phase5-lcd.md**](modules/face-phase5-lcd.md) — dokumentacja fazy 5 implementacji (sink LCD RAW)
- [**modules/sim.md**](modules/sim.md) — symulator 2D Rider-Pi, testowanie algorytmów nawigacji

---

## Dokumentacja skryptów operacyjnych

> **Uwaga:** Skrypty zostały przeniesione z `ops/` i `tools/` do `scripts/` (patrz [../scripts/README.md](../scripts/README.md)).  
> Dokumentacja w `docs/ops/` opisuje funkcjonalność (pozostaje aktualna), ale ścieżki odnoszą się do nowej lokalizacji.

Skrypty operacyjne dla zarządzania systemem i usługami:

- [**ops/README.md**](ops/README.md) — **indeks skryptów** (konwencje, bezpieczeństwo, kody wyjścia)
- [**ops/voice-scripts.md**](ops/voice-scripts.md) — sys_voice-*.sh (uruchamianie aplikacji głosowej)
- [**ops/systemd-scripts.md**](ops/systemd-scripts.md) — sys_control.sh, systemd-sync.sh (zarządzanie usługami)
- [**ops/display-scripts.md**](ops/display-scripts.md) — sys_lcd-control.py, sys_led-control.py (kontrola wyświetlacza)
- [**ops/camera-scripts.md**](ops/camera-scripts.md) — sys_camera-*.sh (zarządzanie kamerą)
- [**ops/monitoring-scripts.md**](ops/monitoring-scripts.md) — diag_metrics.sh, diag_stream.sh (monitorowanie)
- [**ops/utility-scripts.md**](ops/utility-scripts.md) — testy, diagnostyka XGO, demo, narzędzia

### Testy usług systemd

Dokumentacja testowania i walidacji plików `.service`:

- [**SYSTEMD_SERVICES_MAPPING.md**](SYSTEMD_SERVICES_MAPPING.md) — mapowanie usług systemd → skrypty, status po refaktoryzacji
- [**SYSTEMD_SERVICES_INVENTORY.md**](SYSTEMD_SERVICES_INVENTORY.md) — pełna inwentaryzacja wszystkich jednostek systemd (ExecStart, status walidacji)
- [**ops/systemd-scripts.md**](ops/systemd-scripts.md) — szczegółowa dokumentacja narzędzi walidacji

**Dostępne testy:**

1. **Testy statyczne** (bez systemd):
   - `scripts/diag_validate-systemd-paths.py` — walidacja ścieżek w ExecStart
   - `scripts/diag_systemd-smoke.sh` — kompleksowy test bash
   - `pytest tests/test_systemd_services.py` — testy pytest

2. **Testy smoke** (wymagają systemd):
   - `SYSTEMD_SMOKE_TESTS=1 pytest tests/test_systemd_smoke.py` — weryfikacja z systemd

**Uruchamianie lokalnie:**

```bash
# Szybka walidacja (bez zależności)
bash scripts/diag_systemd-smoke.sh

# Pełny zestaw pytest
pip install pytest pytest-timeout
pytest tests/test_systemd_services.py -v

# Z systemd (na robocie)
SYSTEMD_SMOKE_TESTS=1 pytest tests/test_systemd_smoke.py -v
```

Więcej informacji: [SYSTEMD_SERVICES_MAPPING.md](SYSTEMD_SERVICES_MAPPING.md#testing)

---

## Dokumentacja konfiguracji (`config/*`)

Parametry konfiguracji dla wszystkich modułów:

- [**config/README.md**](config/README.md) — **indeks parametrów** (hierarchia, precedencja, polityka sekretów)
- [**config/voice.md**](config/voice.md) — voice_openai_file.toml, voice_openai_streaming.toml (ASR, TTS, Chat)
- [**config/face.md**](config/face.md) — face.toml (geometria buźki, emocje, animacje)
- [**config/alsa.md**](config/alsa.md) — asoundrc.wm8960, wm8960-apply.sh (konfiguracja ALSA)

---

## Dokumentacja audio

Konfiguracja i wykorzystanie kart dźwiękowych:

- [**wm8960.md**](audio/wm8960.md) — konfiguracja karty WM8960 dla dupleksowego strumieniowania audio (ALSA, troubleshooting)

---

## Raporty implementacji

Podsumowania zakończonych etapów prac:

- [**completion-report.md**](_pr_summaries/completion-report.md) — raport końcowy projektu
- [**implementation-summary.md**](_pr_summaries/implementation-summary.md) — podsumowanie implementacji
- [**simulator-summary.md**](_pr_summaries/simulator-summary.md) — podsumowanie implementacji symulatora 2D
- [**sim1-implementation-summary.md**](_pr_summaries/sim1-implementation-summary.md) — raport z implementacji SIM-1 (rdzeń środowiska i renderowanie mapy)
- [**sim3-implementation.md**](_pr_summaries/sim3-implementation.md) — raport z implementacji SIM-3

---

## Release Notes

Historia wydań projektu:

- [**v0.6.md**](release-notes/v0.6.md) — wersja 0.6
- [**v0.5.3.md**](release-notes/v0.5.3.md) — wersja 0.5.3
- [**v0.5.2.md**](release-notes/v0.5.2.md) — wersja 0.5.2

---

## Jak dodawać nową dokumentację

Przy dodawaniu nowych dokumentów należy przestrzegać następujących zasad:

### 1. Wybór lokalizacji

- **Katalog główny** — tylko dokumenty o zasięgu ogólnym (wizja, architektura, working agreements)
- **`docs/apps/`** — dokumentacja modułów aplikacyjnych (`apps/*`)
- **`docs/ops/`** — dokumentacja skryptów operacyjnych (skrypty w `scripts/`)
- **`docs/config/`** — dokumentacja parametrów konfiguracji (`config/*`)
- **`docs/modules/`** — dokumentacja modułów (legacy — nowe dokumenty powinny iść do `docs/apps/`)
- **`docs/audio/`** — konfiguracja sprzętu audio
- **`docs/summaries/`** — raporty z zakończonych prac (obecnie `docs/_pr_summaries/`)
- **`docs/release-notes/`** — informacje o wydaniach

### 2. Konwencja nazewnicza

- Używaj **kebab-case** dla nazw plików: `nazwa-modułu.md`
- Unikaj wielkich liter i podkreślników w nazwach plików
- Nazwy powinny być opisowe i jednoznaczne

### 3. Struktura dokumentu

Każdy dokument powinien zawierać:

1. **Nagłówek H1** z tytułem
2. **Krótki opis** — co dokument zawiera (1-2 zdania)
3. **Sekcje tematyczne** — logiczny podział treści
4. **Przykłady** — konkretne przykłady użycia tam, gdzie to stosowne
5. **Odnośniki** — linki do powiązanych dokumentów

### 4. Język

- Dokumentacja jest prowadzona **w języku polskim**
- Nazwy techniczne (klasy, metody, komendy CLI) pozostają w oryginale
- Kod i komendy shell nie są tłumaczone

### 5. Aktualizacja indeksu

Po dodaniu nowego dokumentu **zaktualizuj ten plik** (`docs/README.md`), dodając odnośnik w odpowiedniej sekcji.

### 6. Linki relatywne

- Wszystkie linki między dokumentami powinny być **relatywne**
- Testuj działanie linków lokalnie przed commitem
- Linki powinny działać zarówno lokalnie, jak i na GitHubie

### 7. Formatowanie

- Używaj składni Markdown zgodnie z konwencjami projektu
- Zachowaj spójność formatowania z istniejącymi dokumentami
- Stosuj bloki kodu z określeniem języka: \`\`\`python, \`\`\`bash, \`\`\`toml

---

## Narzędzia i weryfikacja

### Sprawdzenie linków

Aby sprawdzić poprawność linków w dokumentacji:

```bash
# Wyszukaj wszystkie linki relatywne i sprawdź ich istnienie
rg -n -o '\[[^]]+\]\((?!http)([^)]+)\)' --glob '*.md' | while IFS=: read -r file _ path; do
  p="${path%)}"; [ -f "$(dirname "$file")/$p" ] || echo "BROKEN LINK: $file -> $p";
done
```

### Linting dokumentacji

```bash
# Sprawdź formatowanie Markdown (jeśli używasz markdownlint)
markdownlint docs/**/*.md

# Testy doctestów w dokumentacji
pytest --doctest-glob="*.md" --doctest-modules -q
```

### Spójność z kodem

Regularnie weryfikuj, czy dokumentacja jest zgodna z kodem:

```bash
# Uruchom skrypt sprawdzający spójność (jeśli dostępny)
python scripts/doc_sync_check.py
```

---

## Kontakt i wsparcie

- **Issues**: Zgłaszanie błędów i sugestii przez [GitHub Issues](https://github.com/mpieniak01/Rider-Pi/issues)
- **Pull Requests**: Propozycje zmian w dokumentacji są mile widziane

---

**Ostatnia aktualizacja**: 2025-10 (aktualizacja po reorganizacji struktury: ops/tools/ → scripts/)  
**Wersja dokumentacji**: zgodna z kodem głównym (branch `main`)
