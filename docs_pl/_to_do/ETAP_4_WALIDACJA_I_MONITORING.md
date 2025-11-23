# Etap 4 – Walidacja funkcjonalna i monitoring scenariuszy

## Podsumowanie wykonanych prac
- **Monitoring scenariuszy** – `FeatureManager` udostępnia `describe_features()` i `state_snapshot()` (trwały plik `/run/rider/feature_state.json`). API `/api/logic/state` oraz CLI (`scripts/robot_ctl.py status`) umożliwiają szybkie sprawdzenie aktywnych scenariuszy, a panel `/web/control.html` pod nagłówkiem „Funkcje” pokazuje listę uruchomionych targetów i ostrzeżenia o brakujących usługach.
- **API `/api/logic/features` i `/api/logic/state`** – pierwszy endpoint zwraca katalog scenariuszy, drugi – aktualnie aktywne targety wraz z metadanymi. To zastępuje ręczne przeglądanie `/svc` i jest bazą dla panelu i CLI.
- **Regresja automatyczna** – rozszerzono testy `tests/test_features_core.py` oraz `tests/test_features_api.py` o przypadki pokrywające nową funkcjonalność (status usług, aliasy, snapshot stanu). Uruchomiono `pytest tests/test_features_core.py tests/test_features_api.py` – zestaw przechodzi w całości.

## Wnioski
Etap 4 (walidacja/monitoring) został zrealizowany w warstwie programistycznej: App Logic Core potrafi raportować scenariusze z perspektywy systemd, a API udostępnia te dane operatorom. Pozostałe elementy etapu (testy na fizycznym urządzeniu, uzupełnienie `/svc`) wymagają już tylko operacyjnego uruchomienia nowego API w panelu i porównania z realnym zachowaniem robota.

## Następny krok (Etap 5 – Deprecjacja legacy)
- Przygotować katalog `systemd/legacy` i przenieść do niego stare jednostki (`rider-face.service`, `rider-edge-preview.service`, `rider-ssd-preview.service` itp.).
- Zredukować listę aktywnych usług w repo do tych opisanych w tabeli TO-BE (targety + komponenty komunikacyjne).
- Opracować `docs_pl/UPGRADE_SCENARIOS.md` z instrukcją migracji operatora (stop legacy → start targetów → test scenariuszy).
