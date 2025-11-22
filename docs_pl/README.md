# Dokumentacja Rider-Pi Apps

> Centralny indeks dokumentacji projektu **Rider-Pi Apps** — oprogramowania rozszerzającego możliwości urządzenia Rider-Pi.

## 🚀 Szybki start

Nowy w projekcie? Zacznij tutaj:

1. [**../README.md**](../README.md) — główny README projektu (instalacja, pierwsze kroki)
2. [**PROJECT.md**](PROJECT.md) — wizja projektu, cele biznesowe, roadmapa
3. [**ARCHITECTURE.md**](ARCHITECTURE.md) — architektura systemu, porty, przepływy danych
4. [**ARCHITECTURE_DIAGRAM.md**](ARCHITECTURE_DIAGRAM.md) — diagramy architektury

---

## 📚 Mapa dokumentacji

### 📖 Dokumenty główne

- [**ARCHITECTURE.md**](ARCHITECTURE.md) — główna architektura systemu
- [**ARCHITECTURE_DIAGRAM.md**](ARCHITECTURE_DIAGRAM.md) — diagramy architektury
- [**PROJECT.md**](PROJECT.md) — wizja projektu, cele biznesowe
- [**WORKING-AGREEMENTS.md**](WORKING-AGREEMENTS.md) — ustalenia robocze zespołu
- [**AGENT.md**](AGENT.md) — kontrakt dla asystenta kodu
- [**OFFLOAD_PROVIDER_PROTOCOL.md**](OFFLOAD_PROVIDER_PROTOCOL.md) — kontrakt Pi ↔ PC (offload)

### 🚀 Aplikacje ([`apps/`](apps/))

Dokumentacja wszystkich modułów aplikacyjnych — pełna lista w [**apps/README.md**](apps/README.md).

Główne moduły:
- [**voice.md**](apps/voice.md) — pełny stos głosowy (ASR, TTS, VAD, KWS, chat)
- [**vision.md**](apps/vision.md) — detekcja obiektów (HOG, TFLite, ROI)
- [**face.md**](apps/face.md) — API statycznego renderu buźki
- [**face-lcd.md**](apps/face-lcd.md) — renderowanie buźki na panelu LCD
- [**chat.md**](apps/chat.md) — chat z OpenAI
- [**motion.md**](apps/motion.md) — bridge ruchu
- [**simulator.md**](apps/simulator.md) — symulator 2D Rider-Pi
- [**camera.md**](apps/camera.md) — preview kamery z detekcją twarzy
- [**navigator.md**](apps/navigator.md), [**mapper.md**](apps/mapper.md), [**odometry.md**](apps/odometry.md) — nawigacja i mapowanie
- [**nlu.md**](apps/nlu.md) — rozpoznawanie intencji
- [**safety.md**](apps/safety.md) — emergency stop
- [**demos.md**](apps/demos.md), [**choreographer.md**](apps/choreographer.md) — demonstracje ruchu
- [**ui.md**](apps/ui.md), [**launcher.md**](apps/launcher.md), [**menu.md**](apps/menu.md) — interfejs użytkownika
- [**draw.md**](apps/draw.md), [**hw.md**](apps/hw.md) — prymitywy renderowania

> **App Logic Core**: logika funkcji/feature'ów jest eksponowana przez `apps/app_logic_core` (FeatureManager) i używana przez API/CLI/UI.

### ⚙️ Konfiguracja ([`config/`](config/))

Parametry konfiguracji dla wszystkich modułów — szczegóły w [**config/README.md**](config/README.md).

- [**config/POLICY.md**](config/POLICY.md) — **polityka konfiguracji i sekretów** (single source of truth)
- [**config/voice.md**](config/voice.md) — konfiguracja voice (ASR, TTS, Chat)
- [**config/face.md**](config/face.md) — konfiguracja face (geometria buźki, emocje, animacje)
- [**config/alsa.md**](config/alsa.md) — konfiguracja ALSA
- [**config/validation.md**](config/validation.md) — walidacja konfiguracji
- [**CONFIG.md**](CONFIG.md) — główny dokument konfiguracji

### 🔧 Skrypty operacyjne ([`ops/`](ops/))

Dokumentacja skryptów operacyjnych — szczegóły w [**ops/README.md**](ops/README.md).

> **Uwaga:** Skrypty zostały przeniesione z `ops/` i `tools/` do `scripts/` (patrz [../scripts/README.md](../scripts/README.md)). Dokumentacja w `docs_pl/ops/` pozostaje aktualna, ale ścieżki odnoszą się do nowej lokalizacji.

- [**ops/voice-scripts.md**](ops/voice-scripts.md) — sys_voice-*.sh
- [**ops/systemd-scripts.md**](ops/systemd-scripts.md) — sys_control.sh, systemd-sync.sh
- [**ops/display-scripts.md**](ops/display-scripts.md) — sys_lcd-control.py, sys_led-control.py
- [**ops/camera-scripts.md**](ops/camera-scripts.md) — sys_camera-*.sh
- [**ops/monitoring-scripts.md**](ops/monitoring-scripts.md) — diag_metrics.sh, diag_stream.sh
- [**ops/utility-scripts.md**](ops/utility-scripts.md) — testy, diagnostyka

### 🌐 API REST ([`api-specs/`](api-specs/))

Specyfikacja REST API — szczegóły w [**api-specs/README.md**](api-specs/README.md).

- [**api-specs/control.md**](api-specs/control.md) — API kontroli systemu
- [**api-specs/navigator.md**](api-specs/navigator.md) — API nawigacji

### 🔊 Audio ([`audio/`](audio/))

Konfiguracja sprzętu audio:
- [**audio/wm8960.md**](audio/wm8960.md) — konfiguracja karty WM8960 (ALSA, troubleshooting)

### 🚦 Systemd

Dokumentacja usług systemd:
- [**SYSTEMD_SERVICES_MAPPING.md**](SYSTEMD_SERVICES_MAPPING.md) — mapowanie usług systemd → skrypty
- [**SYSTEMD_SERVICES_INVENTORY.md**](SYSTEMD_SERVICES_INVENTORY.md) — inwentaryzacja jednostek systemd

### 🔌 Integracje

Dokumentacja integracji zewnętrznych:
- [**google-home-integration.md**](google-home-integration.md) — integracja z Google Home
- [**integracja-google-gemini.md**](integracja-google-gemini.md) — integracja z Google Gemini
- [**ecosystem-google.md**](ecosystem-google.md) — ekosystem Google
- [**google/home_command.md**](google/home_command.md) — komendy Google Home

### 📊 Inne dokumenty

- [**DOCS_AUTO_UPDATE.md**](DOCS_AUTO_UPDATE.md) — automatyczna aktualizacja dokumentacji
- [**FOLLOW_ME_TRACKING.md**](FOLLOW_ME_TRACKING.md) — tracking dla trybu Follow Me
- [**NAVIGATION_VISUALIZATION.md**](NAVIGATION_VISUALIZATION.md) — wizualizacja nawigacji
- [**PTT_USAGE.md**](PTT_USAGE.md) — użycie Push-to-Talk
- [**QUALITY_GUARDS.md**](QUALITY_GUARDS.md) — guardy jakości kodu
- [**resource_diagnostics.md**](resource_diagnostics.md) — diagnostyka zasobów
- [**voice_metrics.md**](voice_metrics.md) — metryki modułu voice
- [**drivers/README.md**](drivers/README.md) — dokumentacja sterowników
- [**scripts/README.md**](scripts/README.md) — dokumentacja skryptów
- [**ui/README.md**](ui/README.md), [**ui/control.md**](ui/control.md) — dokumentacja UI

### 📦 Release Notes

Historia wydań projektu — w katalogu [`release-notes/`](release-notes/):
- [**v0.6.md**](release-notes/v0.6.md)
- [**v0.5.3.md**](release-notes/v0.5.3.md)
- [**v0.5.2.md**](release-notes/v0.5.2.md)

### 📦 Archiwum historyczne ([`archive/`](archive/))

Raporty historyczne i dokumentacja przestarzała znajdują się w katalogu [**archive/**](archive/):
- Raporty z PR (`archive/_pr_summaries/`)
- Listy zadań (`archive/_todo/`)
- Podsumowania implementacji (IMPLEMENTATION_*.md)
- Legacy dokumentacja modułów

---

## 📝 Jak dodawać nową dokumentację

### 1. Wybór lokalizacji

- **Katalog główny `docs_pl/`** — tylko dokumenty o zasięgu ogólnym (wizja, architektura, working agreements)
- **`docs_pl/apps/`** — dokumentacja modułów aplikacyjnych
- **`docs_pl/ops/`** — dokumentacja skryptów operacyjnych
- **`docs_pl/config/`** — dokumentacja parametrów konfiguracji
- **`docs_pl/api-specs/`** — specyfikacje REST API
- **`docs_pl/audio/`** — konfiguracja sprzętu audio
- **`docs_pl/archive/`** — raporty historyczne i dokumentacja przestarzała
- **`docs_pl/release-notes/`** — informacje o wydaniach

### 2. Konwencja nazewnicza

- Używaj **kebab-case** dla nazw plików: `nazwa-modulu.md`
- Unikaj wielkich liter i podkreślników w nazwach plików
- Nazwy powinny być opisowe i jednoznaczne

### 3. Struktura dokumentu

Każdy dokument powinien zawierać:

1. **Nagłówek H1** z tytułem
2. **Krótki opis** — co dokument zawiera (1-2 zdania)
3. **Sekcje tematyczne** — logiczny podział treści
4. **Przykłady** — konkretne przykłady użycia
5. **Odnośniki** — linki do powiązanych dokumentów

### 4. Język

- Dokumentacja jest prowadzona **w języku polskim**
- Nazwy techniczne (klasy, metody, komendy CLI) pozostają w oryginale
- Kod i komendy shell nie są tłumaczone

### 5. Aktualizacja indeksu

Po dodaniu nowego dokumentu **zaktualizuj ten plik** (`docs_pl/README.md`), dodając odnośnik w odpowiedniej sekcji.

### 6. Linki relatywne

- Wszystkie linki między dokumentami powinny być **relatywne**
- Testuj działanie linków lokalnie przed commitem
- Linki powinny działać zarówno lokalnie, jak i na GitHubie

### 7. Formatowanie

- Używaj składni Markdown zgodnie z konwencjami projektu
- Zachowaj spójność formatowania z istniejącymi dokumentami
- Stosuj bloki kodu z określeniem języka: \`\`\`python, \`\`\`bash, \`\`\`toml

---

## 🔍 Narzędzia i weryfikacja

### Sprawdzenie linków

```bash
# Wyszukaj wszystkie linki relatywne i sprawdź ich istnienie
rg -n -o '\[[^]]+\]\((?!http)([^)]+)\)' --glob '*.md' | while IFS=: read -r file _ path; do
  p="${path%)}"; [ -f "$(dirname "$file")/$p" ] || echo "BROKEN LINK: $file -> $p";
done
```

### Linting dokumentacji

```bash
# Sprawdź formatowanie Markdown (jeśli używasz markdownlint)
markdownlint docs_pl/**/*.md

# Testy doctestów w dokumentacji
pytest --doctest-glob="*.md" --doctest-modules -q
```

---

## 💬 Kontakt i wsparcie

- **Issues**: Zgłaszanie błędów i sugestii przez [GitHub Issues](https://github.com/mpieniak01/Rider-Pi/issues)
- **Pull Requests**: Propozycje zmian w dokumentacji są mile widziane

---

**Ostatnia aktualizacja**: 2025-11 (refaktoryzacja struktury: utworzenie archive/, konsolidacja modules/ → apps/)  
**Wersja dokumentacji**: zgodna z kodem głównym (branch `main`)
