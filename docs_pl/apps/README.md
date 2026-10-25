# Indeks aplikacji

Moduły apps/ wykonują aplikacje robota; orkiestracja HTTP i własność zasobów
mają osobne opisy. Obecność modułu nie oznacza jego aktywności, zainstalowanych
zależności ani kwalifikacji fizycznej.

| Obszar | Przewodniki |
| --- | --- |
| Operator i wykonanie | [Ruch](motion.md), [bezpieczeństwo](safety.md), [ręczny odbiór fizyczny](physical-motion.md), [kalibracja](calibration.md), [polecenia z rozmowy](agent-control.md) |
| Obraz | [Kamera](camera.md), [wyłączenie źródła](camera-source-off.md), [wizja](vision.md), [modele percepcji](perception-models.md), [profile nawigacji](navigation-profiles.md) |
| Nawigacja i obserwacja | [Navigator](navigator.md), [mapper](mapper.md), [odometria](odometry.md), [telemetria systemu](system-telemetry.md) |
| Głos i tekst | [Voice](voice.md), [chat](chat.md), [NLU](nlu.md) |
| Ekran i wejścia | [Rysowanie](draw.md), [sink sprzętowy](hw.md), [UI](ui.md), [buźka](face.md), [własność LCD](face-lcd.md), [launcher](launcher.md), [menu](menu.md) |
| Scenariusze programowe | [Choreographer](choreographer.md), [dema](demos.md), [symulator](simulator.md) |

Rzeczywiste unity uruchomieniowe opisują [zadania/usługi/zasoby](../ZADANIA_USLUGI_ZASOBY.md)
i [mapowanie systemd](../SYSTEMD_SERVICES_MAPPING.md). Nie istnieje uniwersalne
polecenie rider-<moduł>.service ani python -m apps.<nazwa>.
Zachowaj jednego właściciela UART/LCD; odczyt przewodnika lub panelu nie startuje zadania.

Testy automatyczne używają istniejącego venv WSL, odizolowanego BUS i jawnych atrap.
Nazwa dema ani DRY_RUN nie dowodzą izolacji fizycznej.
[Polityka środowisk](../POLITYKA_SRODOWISK.md) · [Konfiguracja](../config/README.md) ·
[Skrypty obsługi](../ops/README.md).
