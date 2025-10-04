# Rider-Pi – sekwencja startu usług (stan: 2025‑10‑04)

> **Cel:** Zapis bieżącej kolejności uruchamiania usług i minimalnych zależności. Nie jest to dziś krytyczne, ale przy **finalnej paczce instalacyjnej** chcemy zagwarantować przewidywalny rozruch i dostępne SSH/NET od startu.

---

## 1) Obserwacja z `systemd-analyze critical-chain`
Odczyt z urządzenia:
```
multi-user.target @~26.3s
└─rider-vision.service
  └─rider-broker.service
    └─rider-boot-prepare.service @~5.6s +20.6s
      └─basic.target → ... → local-fs.target → ...
```
**Wnioski:**
- Łańcuch widoczny na starcie jest zdominowany przez Ridera (`rider-boot-prepare → rider-broker → rider-vision`).
- Usługi sieciowe (`wifi-unblock`, `wpa_supplicant`, `dhcpcd`) **nie są** wprost w krytycznym łańcuchu; sieć może dojść chwilę „obok”.

## 2) Aktualny stack sieciowy
- `wifi-unblock.service` (z repo, **enabled**): odblokowuje radio i podnosi `wlan0` **przed** siecią.
- `wpa_supplicant.service` (enabled): zestawia Wi‑Fi wg istniejącego `/etc/wpa_supplicant/wpa_supplicant.conf`.
- `dhcpcd.service` (enabled): przydziela IP (DHCP).
- **Brak zależności Ridera** od `network-online.target` (świadomie – dziś niekrytyczne).

## 3) Stan minimalnych zależności (działa stabilnie)
- `wifi-unblock.service`: `Before=connman.service network-pre.target` + `ip link set wlan0 up`.
- `wpa_supplicant.service` i `dhcpcd.service`: uruchamiane niezależnie od Ridera.
- Rider startuje bez oczekiwania na IP (możliwe, że IP wskakuje chwilę później, ale SSH już działa po kilku sekundach).

---

## 4) Zalecenia na **finalną paczkę instalacyjną** (deterministyczny rozruch)

### Wariant A (rekomendowany): czekamy na "network‑online"
- **Włączyć:** `dhcpcd-wait-online.service` (jeśli dostępny w systemie).
- **Drop‑in dla `rider-boot-prepare.service`:**
  ```ini
  [Unit]
  Wants=network-online.target
  After=network-online.target
  ```
- **Efekt:** Rider wystartuje dopiero, gdy system ma już IP. Przydatne dla użytkowników „plug‑and‑play”.

### Wariant B (lekki): tylko kolejność bez twardego czekania
- **Drop‑in dla `rider-boot-prepare.service`:**
  ```ini
  [Unit]
  After=wifi-unblock.service wpa_supplicant.service dhcpcd.service
  ```
- **Efekt:** Rider rusza po starcie usług sieciowych, ale nie blokujemy boota, jeśli DHCP chwilę trwa.

> W obu wariantach **nie dotykamy** `wpa_supplicant.conf` – korzystamy z istniejącego.

---

## 5) Kontrola jakości (manual QA) po instalacji
- `rfkill list` → `Soft blocked: no`.
- `iw dev wlan0 link` → `Connected to …`, **SSID widoczny**.
- `ip addr show wlan0` → `inet 192.168.x.x/24`.
- `systemd-analyze critical-chain` → w wariancie A pojawia się gałąź `network-online.target` **przed** `rider-boot-prepare.service`.

---

## 6) Co dołączamy do paczki (artefakty)
- `systemd/wifi-unblock.service` (już w repo; symlinkowany przez `ops/systemd_sync.sh`).
- `systemd/drop-ins/rider-boot-prepare.service.d/`:
  - `after-network.conf` (wariant B) **lub** `wait-online.conf` (wariant A).
- `ops/systemd_sync.sh` – dopisana allowlista dla powyższych plików.

---

## 7) Definition of Ready (DoR) dla paczki
- [ ] `wifi-unblock.service` – **enabled** po `systemd_sync.sh`.
- [ ] `wpa_supplicant.service` + `dhcpcd.service` – **enabled**.
- [ ] Wybrany wariant: **A** (z `network-online`) **lub** **B** (kolejność bez wait) – drop‑in obecny i synchronizowany.
- [ ] `critical-chain` potwierdza oczekiwaną kolejność (zależnie od wariantu).
- [ ] SSH dostępne do 10 s po starcie.

---

## 8) Komendy diagnostyczne (ściąga)
```bash
sudo systemd-analyze critical-chain
systemctl status wifi-unblock.service wpa_supplicant.service dhcpcd.service --no-pager -l
systemctl list-dependencies --reverse multi-user.target | grep -E "wifi|wpa|dhcp|rider"
```

> Dokument będzie rozwijany w trakcie przygotowania paczki instalacyjnej. Data: 2025‑10‑04.