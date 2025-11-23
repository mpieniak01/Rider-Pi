# UPGRADE_SCENARIOS.md – przewodnik migracji scenariuszy

Ten dokument opisuje, jak przejść z podejścia „ręczne uruchamianie unitów systemd” do sterowania scenariuszami S0–S11 przez App Logic Core i FeatureManagera.

## 1. Przygotowanie środowiska

1. **Zatrzymaj stare preview/face**  
   ```bash
   sudo systemctl stop rider-edge-preview.service rider-ssd-preview.service rider-face.service || true
   ```
2. **Uruchom repo-first sync** (`scripts/systemd-sync.sh`) – skrypt usunie przestarzałe linki i zainstaluje tylko wspierane jednostki. Legacy pliki (`rider-face`, `rider-edge-preview`, `rider-ssd-preview`) znajdują się teraz w `systemd/legacy/` i nie są linkowane automatycznie.
3. **Zaktualizuj konfiguracje** (`systemd/robot.env`, `config/*.toml`) zgodnie z docelowymi scenariuszami.

## 2. Start scenariuszy przez App Logic

Po wykonaniu powyższych kroków, wszystkie funkcje robota należy uruchamiać przez CLI/API:

```bash
# Sterowanie manualne (S1)
sudo python3 scripts/robot_ctl.py start s1_manual

# Follow Me – twarz (S3)
sudo python3 scripts/robot_ctl.py start s3_follow_me_face

# Rekonesans (S4)
sudo python3 scripts/robot_ctl.py start s4_recon

# Wyłączenie scenariuszy
sudo python3 scripts/robot_ctl.py stop s3_follow_me_face

# Podgląd aktywnych scenariuszy
sudo python3 scripts/robot_ctl.py status
```

API analogiczne: `POST /api/logic/feature/<name> {"enabled": true|false}`.

## 3. Walidacja po migracji

1. Wejdź na `/svc` oraz `/api/logic/features`, aby potwierdzić, że wymagane usługi są aktywne.
2. Uruchom smoke testy (np. `pytest tests/test_features_core.py tests/test_features_api.py`) i podstawowe tryby z panelu (`S0`, `S1`, `S3`, `S4`).
3. Legacy jednostki:
   - pozostają w `systemd/legacy/` (można je ręcznie skopiować do `/etc/systemd/system`, jeśli są potrzebne w trybie DEV/S11),
   - nie są już enumerowane przez `/svc` ani targety produkcyjne.

## 4. Najczęstsze problemy

| Objaw | Przyczyna | Rozwiązanie |
|-------|-----------|-------------|
| Panel pokazuje brak kamery | Legacy preview został usunięty, a `camera-capture` nie wystartował | uruchom `camera-capture@raw.service` (tymczasowo) lub sprawdź konfigurację CAPTURE_MODE |
| Feature API zwraca `unknown_feature` | Literówka w nazwie scenariusza | sprawdź listę `GET /api/logic/features` |
| Systemd-sync usunął potrzebny preview | Legacy pliki dostępne są w `systemd/legacy/` – skopiuj ręcznie lub dodaj do lokalnej allow-listy (dev only) |

Dokument będzie aktualizowany wraz z kolejnymi etapami migracji (Etap 1–4). Wszelkie nowe scenariusze powinny być dopisywane do tabel App Logic Core i weryfikowane przez powyższy workflow.
