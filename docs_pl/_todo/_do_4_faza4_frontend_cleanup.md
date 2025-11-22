# Faza 4 – Frontend + Cleanup (_do)

## Zakres
- `web/control.html` korzysta z `/api/logic/feature/<name>` (FeatureManager) zamiast sekwencji systemd; tabela usług pozostaje, ale pobiera aktualne stany z `/svc` i korzysta ze zaktualizowanej logiki systemd_ctrl.
- Legacy endpointy `/vision/follow/face|hand` zwracają 410 i kierują na nowe API.
- Dodano odświeżanie tabeli usług oraz akcje start/stop/restart/enable/disable przez `/svc/<unit>`; kolejka ruchu ma prosty flush przez `api/control`.

## Testy
- `python -m pytest tests/test_systemd_services.py tests/test_features_core.py tests/test_features_api.py`

## Uwagi
- UI jest zgodne z nową warstwą core; dalsze zmiany w UX można prowadzić niezależnie od logiki systemd.
