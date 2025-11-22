# Faza 2 – Core Business Logic (_do)

## Zakres
- Utworzono `services/core/features.py` z rejestrem funkcji (`face_tracking`, `hand_tracking`, `recon`) oraz `FeatureManagerem` odpowiedzialnym za sekwencje start/stop usług, wymuszanie podglądu CAM i publikowanie trybu śledzenia przez ZMQ.
- Zapewniono API dla logiki: `FeatureManager.set_feature(name, enabled)` zwraca wynik kroków i publikacji zdarzeń.

## Testy
- `python -m pytest tests/test_features_core.py`

## Uwagi
- Logika funkcji jest już wyciągnięta do warstwy core; integracja z API/CLI/UI nastąpi w kolejnych fazach.
