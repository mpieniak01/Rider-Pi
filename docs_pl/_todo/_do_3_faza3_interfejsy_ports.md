# Faza 3 – Interfejsy (Ports & Adapters) (_do)

## Zakres
- Dodano API `/api/logic/feature/<name>` w `services/api_core/features_api.py`, oparte o `FeatureManager` z warstwy core.
- Zarejestrowano trasę w `services/api_server.py` (POST/OPTIONS).
- Utworzono CLI `scripts/robot_ctl.py` umożliwiające `start/stop` funkcji (`face_tracking`, `hand_tracking`, `recon`) z linii poleceń.

## Testy
- `python -m pytest tests/test_features_api.py`

## Uwagi
- API i CLI korzystają z tego samego `FeatureManagera`; UI nadal wymaga aktualizacji (Faza 4) przed usunięciem legacy endpointów.
