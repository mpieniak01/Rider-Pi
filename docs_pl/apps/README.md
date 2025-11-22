# Dokumentacja modułów aplikacyjnych (`apps/*`)

> Indeks dokumentacji wszystkich modułów aplikacyjnych w katalogu `apps/`

## Spis modułów

### Komunikacja i NLU
- [**chat.md**](chat.md) — moduł chat: audio.transcript → OpenAI → tts.speak
- [**nlu.md**](nlu.md) — rozpoznawanie intencji ruchu z transkrypcji głosowych (PL)

### Wizja i kamera
- [**camera.md**](camera.md) — preview kamery z detekcją twarzy na LCD
- [**vision.md**](vision.md) — detekcja obiektów (HOG, TFLite, ROI)

### Interfejs użytkownika
- [**draw.md**](draw.md) — prymitywy renderowania buźki (arc, eyes, mouth)
- [**hw.md**](hw.md) — sink LCD do wyświetlania na sprzęcie
- [**ui.md**](ui.md) — przyciski, konfiguracja UI, emocje buźki
- [**launcher.md**](launcher.md) — menu startowe na 4 przyciski
- [**menu.md**](menu.md) — menu nawigacyjne (dema, autonomia, teleop)

### Ruch i bezpieczeństwo
- [**motion.md**](motion.md) — bridge ruchu: motion.cmd → XGO adapter
- [**safety.md**](safety.md) — emergency stop (E-STOP)

### Demonstracje
- [**demos.md**](demos.md) — gotowe demonstracje (trajektorie, lemniskata)

### Voice
⚠️ **Uwaga:** Moduł `apps/voice` ma dedykowaną pełną dokumentację w [`do./voice.md`](./voice.md)

## Konwencje

Każdy dokument modułu zawiera:
- **Opis:** Co robi moduł, główne klasy i funkcje
- **Przepływ danych:** Wejście → Przetwarzanie → Wyjście
- **Konfiguracja:** Parametry ENV/CLI, zależności do plików w `config/`
- **Przykład użycia:** Jak uruchomić moduł (CLI, systemd)
- **Błędy i diagnostyka:** Typowe błędy, logi, troubleshooting

## Zależności między modułami

```
Przepływ danych voice → chat/nlu:
  voice (ASR) → audio.transcript → chat → tts.speak
                                  ↘ nlu → motion.cmd

Przepływ UI:
  ui.buttons → launcher/menu → system.mode
  draw + hw.sink_lcd → wyświetlacz fizyczny
  
Przepływ wizji:
  camera → vision.detector → motion commands
```

## Uruchamianie modułów

Większość modułów może być uruchomiona jako:

```bash
# Bezpośrednio jako moduł Python
python -m apps.<nazwa>

# Lub przez systemd (jeśli skonfigurowane)
sudo systemctl start rider-<nazwa>.service
```

Zobacz [docs/ops/systemd-scripts.md](../ops/systemd-scripts.md) dla zarządzania usługami.

---

**Related docs:**
- [config/POLICY.md](../config/POLICY.md) — polityka konfiguracji
- [docs/ops/](../ops/) — skrypty operacyjne
- [docs/config/](../config/) — parametry konfiguracji

**Ostatnia aktualizacja:** 2025-01
