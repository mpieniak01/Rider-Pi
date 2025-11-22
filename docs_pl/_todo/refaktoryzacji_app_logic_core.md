# Plan Wdrożenia

## Refaktoryzacja Logiki Biznesowej – App Logic Core

**Cel główny:**
Przeniesienie logiki zarządzania zależnościami usług (systemd orchestration) z warstwy Frontend (HTML/JS) oraz API (Flask) do dedykowanej warstwy Core (Python). Umożliwienie sterowania funkcjami robota (np. "Hand Tracking") zarówno przez API, jak i niezależne CLI.

---

# FAZA 1 — Fundament Systemowy (Low-Level)

### Cel: Odseparowanie logiki `systemctl` od HTTP (Flask).

## 1.1 – Moduł `common/systemd_ctrl.py`

**Opis:**
Nowy moduł odpowiedzialny za komunikację z systemd. Nie zwraca Response/JSON — tylko wartości bool lub rzuca wyjątki.

**Wymagania:**

* `run_unit_action(unit: str, action: str) -> bool`
* `is_active(unit: str) -> bool`
* Obsługa `sudo -n` oraz opcjonalnego `scripts/sys_control.sh`

**Plik:** `common/systemd_ctrl.py`

## 1.2 – Refaktoryzacja `services/api_core/services_api.py`

**Opis:**
Zastąpić dotychczasowe subprocess → `common.systemd_ctrl`.

**Warunek akceptacji:** Endpointy `/api/services` działają jak wcześniej.

---

# FAZA 2 — Core Business Logic (Single Source of Truth)

### Cel: Zdefiniowanie „Funkcji” (Features) w jednym miejscu.

## 2.1 – Moduł `services/core/features.py`

**Opis:** Centralne sterowanie funkcjami.

### FEATURE_REGISTRY

* `face_tracking`: tracker + tracking-controller, tryb `face`, `ensure_cam=True`
* `hand_tracking`: tracker + tracking-controller, tryb `hand`, `ensure_cam=True`
* `recon`: odometry + mapper + navigator + obstacle, `ensure_cam=False`

### Klasa FeatureManager

Metoda: `set_feature(name, enabled)`

**Logika włączania:**

1. Sprawdzenie kamery.
2. Start usług.
3. Wysłanie ZMQ event.

**Logika wyłączania:**

1. ZMQ event.
2. Stop usług (odwrotnie).

**Plik:** `services/core/features.py`

---

# FAZA 3 — Interfejsy (Ports & Adapters)

## 3.1 – CLI: `scripts/robot_ctl.py`

**Użycie:**

```
sudo python3 scripts/robot_ctl.py [start|stop] [feature_name]
```

**Wymagania:**

* obsługa błędów
* jasne logi

## 3.2 – API: `services/api_core/features_api.py`

Endpoint:

```
POST /api/logic/feature/<name>
payload: {"enabled": true}
```

Integracja: rejestracja Blueprintu w `services/api_server.py`.

---

# FAZA 4 — Integracja Frontend + Cleanup

## 4.1 – Aktualizacja `web/control.html`

**Zmiany:**

* Usunąć tablice usług.
* Usunąć logikę sekwencji systemd.
* Wywołania zastąpić:

```
httpPost('/api/logic/feature/' + mode, { enabled: true/false })
```

**Warunek:** UI działa identycznie, JS krótszy o ~50%.

## 4.2 – Cleanup `vision_api.py`

Usunąć:

* `/vision/tracking/mode`
* `/vision/follow/*`

---

# Definition of Done (DoD)

## 1. Niezależność CLI

* `sudo systemctl stop rider-api`
* `sudo python3 scripts/robot_ctl.py start hand_tracking`
* wynik: tracker + tracking-controller wstają, camera OK

## 2. Poprawność UI

* API działa
* klik „Start Hand Tracking” → usługi startują, status Running, brak błędów JS

## 3. Odporność na błędy

* nieistniejąca funkcja → jasny błąd (CLI/API)
* brak tracebacków

## 4. Czystość kodu

* brak `.service` w HTML
* cała logika zależności tylko w `features.py`
