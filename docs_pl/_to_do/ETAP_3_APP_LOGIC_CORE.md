# Etap 3 – Targety scenariuszy i App Logic Core

## Podsumowanie wykonania
- **Targety scenariuszy** – dodano `rider-core.target`, `rider-followme.target` oraz `rider-recon.target`. Każdy target zawiera komplet usług opisanych w scenariuszach S0, S3 i S4 (capture + frame feed + moduły przetwarzania + warstwa ruchu). Dzięki temu `systemctl start rider-followme.target` uruchamia całe Follow Me, a nie pojedyncze units.
- **Integracja z App Logic** – rejestr `FeatureManagera` odwołuje się teraz do targetów zamiast list unitów, a podczas startu funkcji wymagających kamery automatycznie uruchamia również `frame-distributor.service`. Aliasy (`follow_me`, `recon`, `face_tracking`) prowadzą do nowych scenariuszy, więc API/CLI mogą sterować targetami bez zmian w UI.
- **Testy i dokumentacja** – zaktualizowane testy (`tests/test_features_core.py`) pokazują, że start/stop funkcji wywołuje target, zaś dokumentacja (scenariusze, instrukcje ops) odnosi się do `camera-capture@…`, `frame-distributor` i nowych targetów, zamykając etap planu migracji.

## Wnioski
App Logic Core naprawdę zarządza scenariuszami – zamiast sekwencji start/stop pojedynczych usług uruchamia się target systemd składający się z całego pipeline’u. Pozwala to operatorowi przełączać scenariusze jednym wywołaniem (UI/API/CLI), upraszcza rollout i otwiera drogę do dalszej automatyzacji.

## Następny krok
- Kontynuować Etap 4 (walidacja/monitoring) – UI powinno wizualizować status nowych targetów (np. w `/svc` i `/api/logic/features`), a moduły przetwarzania publikować wyniki w spójnych topicach (`tracking.pose`, `obstacle.map`). Warto również odświeżyć `/svc`, by pokazywał aktywne targety obok poszczególnych usług.***
