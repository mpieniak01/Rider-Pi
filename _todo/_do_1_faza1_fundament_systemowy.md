# Faza 1 – Fundament systemowy (_do)

## Zakres
- Dodano warstwę `common/systemd_ctrl.py` do obsługi systemd (status, start/stop/restart z preferencją `scripts/sys_control.sh`).
- `services/api_core/services_api.py` korzysta teraz z warstwy systemowej zamiast bezpośrednich wywołań `subprocess`/`sys_control.sh`.

## Testy
- `pytest tests/test_systemd_services.py`

## Uwagi
- API `/api/services` zachowuje dotychczasowe zachowanie, ale logika systemd jest już w warstwie core.
