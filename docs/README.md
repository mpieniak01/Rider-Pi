# Dokumentacja Rider-Pi Apps

> Centralny indeks dokumentacji projektu **Rider-Pi Apps** — oprogramowania rozszerzającego możliwości urządzenia Rider-Pi.

> **Uwaga**: Raporty historyczne w katalogu `docs/summaries/` mogą pozostać w języku angielskim, ponieważ stanowią zapis wcześniejszych wersji projektu.

## Dokumenty główne (katalog główny)

Najważniejsze dokumenty znajdują się w katalogu głównym projektu:

- [**README.md**](../README.md) — wprowadzenie do projektu, instalacja, szybki start
- [**PROJECT.md**](../PROJECT.md) — wizja projektu, cele biznesowe, roadmapa
- [**ARCHITECTURE.md**](../ARCHITECTURE.md) — architektura systemu, porty, przepływy danych
- [**ARCHITECTURE_DIAGRAM.md**](../ARCHITECTURE_DIAGRAM.md) — diagramy architektury
- [**AGENT.md**](../AGENT.md) — kontrakt dla asystenta kodu, zasady developerskie
- [**WORKING-AGREEMENTS.md**](../WORKING-AGREEMENTS.md) — ustalenia robocze zespołu

---

## Dokumentacja modułów

Szczegółowa dokumentacja poszczególnych modułów systemu:

### Moduł buźki (Face)

- [**face-lcd.md**](modules/face-lcd.md) — renderowanie buźki na panelu LCD ILI9xx (ogólny opis obsługi LCD: tryby, zmienne środowiskowe, benchmark, recovery)
- [**face.md**](modules/face.md) — API statycznego renderu buźki (endpointy HTTP, konfiguracja)
- [**face-phase5-lcd.md**](modules/face-phase5-lcd.md) — dokumentacja fazy 5 implementacji (sink LCD RAW dla animacji twarzy)

### Moduł głosu (Voice)

- [**voice.md**](modules/voice.md) — pełny stos głosowy (ASR, TTS, VAD, KWS, chat), tryby plikowy i strumieniowy

### Symulator (Simulator)

- [**sim.md**](modules/sim.md) — symulator 2D Rider-Pi, testowanie algorytmów nawigacji bez sprzętu

---

## Dokumentacja audio

Konfiguracja i wykorzystanie kart dźwiękowych:

- [**wm8960.md**](audio/wm8960.md) — konfiguracja karty WM8960 dla dupleksowego strumieniowania audio (ALSA, troubleshooting)

---

## Raporty implementacji

Podsumowania zakończonych etapów prac:

- [**completion-report.md**](summaries/completion-report.md) — raport końcowy projektu
- [**implementation-summary.md**](summaries/implementation-summary.md) — podsumowanie implementacji
- [**simulator-summary.md**](summaries/simulator-summary.md) — podsumowanie implementacji symulatora 2D
- [**sim1-implementation-summary.md**](summaries/sim1-implementation-summary.md) — raport z implementacji SIM-1 (rdzeń środowiska i renderowanie mapy)
- [**sim3-implementation.md**](summaries/sim3-implementation.md) — raport z implementacji SIM-3

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
- **`docs/modules/`** — dokumentacja poszczególnych modułów aplikacyjnych
- **`docs/audio/`** — konfiguracja sprzętu audio
- **`docs/summaries/`** — raporty z zakończonych prac
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

**Ostatnia aktualizacja**: 2025-10-04  
**Wersja dokumentacji**: zgodna z kodem głównym (branch `main`)
