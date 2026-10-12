# Dokumentacja Rider-Pi

[Jednolity standard kontraktów Pi/PC](api-specs/contracts.md) — Nowy klient negocjuje kopertę v1 nagłówkiem Accept; przykłady bez negocjacji opisują projekcję legacy. Czas odbioru nie zastępuje czasu pomiaru.


Rider-Pi wykonuje polecenia na sprzęcie i zachowuje lokalne aplikacje robota.
Rider-PC dostarcza panel operatora i dodatkowe przetwarzanie AI. Venom jest
planowanym filarem nadrzędnego sterowania; integracja pozostaje odłożona.

## Zacznij tutaj

- [Wizja projektu](PROJECT.md), [architektura](ARCHITECTURE.md), [diagramy](ARCHITECTURE_DIAGRAM.md).
- [Development](development.md), [wdrożenie i odtwarzanie](WDROZENIE.md).
- [Polityka środowisk, zależności i testów](POLITYKA_SRODOWISK.md).
- [Profile kalibracji i pomiary](apps/calibration.md).
- [Architektura ruchu](apps/motion.md), [blokady i praca z fizycznym robotem](apps/safety.md).
- [Polityka dokumentacji](POLITYKA_DOKUMENTACJI.md), [konfiguracja i sekrety](config/POLICY.md).
- [Dokumentacja angielska](../docs/README.md).

## Interfejsy i aplikacje

- [Studio buźki — podgląd i edytor gestów](FACE_STUDIO.md).

- [Kontrakt providerów Pi ↔ PC](OFFLOAD_PROVIDER_PROTOCOL.md).
- [Indeks API](api-specs/README.md), [sterowanie](api-specs/control.md), [nawigacja](api-specs/navigator.md).
- [Moduły aplikacyjne](apps/README.md), [sterowniki sprzętu](drivers/README.md).
- [Ekrany webowe](ui/README.md), [panel operatora](ui/operator-panel.md), [diagnostyka i wersja w stopce](ui/panel-diagnostyka.md).
- [Follow Me](FOLLOW_ME_TRACKING.md), [wizualizacja nawigacji](NAVIGATION_VISUALIZATION.md).
- [Push-to-talk](PTT_USAGE.md), [metryki głosu](voice_metrics.md), [diagnostyka zasobów](resource_diagnostics.md).

## Konfiguracja i obsługa

- [Indeks konfiguracji](config/README.md), [głos](config/voice.md), [twarz](config/face.md), [walidacja](config/validation.md).
- [Audio WM8960](audio/wm8960.md), [ALSA](config/alsa.md).
- [Skrypty](scripts/README.md), [instrukcje skryptów](ops/README.md), [mapowanie systemd](SYSTEMD_SERVICES_MAPPING.md), [katalog unitów](SYSTEMD_SERVICES_INVENTORY.md).
- [Zadania, usługi i zasoby](ZADANIA_USLUGI_ZASOBY.md), [migracja scenariuszy](UPGRADE_SCENARIOS.md).
- [Google Gemini](ecosystem-google.md), [Google Home](google-home-integration.md), [API Home command](google/home_command.md).
- [Kontrole jakości](QUALITY_GUARDS.md), [ustalenia pracy](WORKING-AGREEMENTS.md), [instrukcje agenta](../AGENT.md).
- Wydania: [v0.6](release-notes/v0.6.md), [v0.5.3](release-notes/v0.5.3.md), [v0.5.2](release-notes/v0.5.2.md).

Publiczne przewodniki opisują projekt i interfejsy. Plany, raporty zadań i wyniki
sprawdzeń konkretnego urządzenia pozostają w ignorowanych katalogach lokalnych.

Wersja polska jest punktem wyjścia; aktualizujemy też instrukcje EN.
Lokalne plany i raporty utrzymujemy tylko w `docs_pl/_to_do/` i `docs_pl/_done/`.

- [Wspólna obsługa zasobów i celów](ARCHITEKTURA_ZASOBOW.md)
