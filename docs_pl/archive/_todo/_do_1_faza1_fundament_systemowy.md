# Faza 1 – Fundament systemowy (_do)

## Zakres
- Dodano warstwę `common/systemd_ctrl.py` do obsługi systemd (status, start/stop/restart z preferencją `scripts/sys_control.sh`).
- `services/api_core/services_api.py` korzysta z warstwy systemowej zamiast własnych wywołań `subprocess`, zachowując dotychczasowy format odpowiedzi API.

## Testy
- `python -m pytest tests/test_systemd_services.py`

## Uwagi
- Endpointy `/api/services` nadal istnieją; logika systemd jest wyłączona z warstwy HTTP, przygotowując grunt pod FeatureManager (Faza 2).
