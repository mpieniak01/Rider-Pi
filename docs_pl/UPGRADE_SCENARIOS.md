# Migracja instalacji scenariuszy

Utrzymywany [kontrakt zadań i zasobów](ZADANIA_USLUGI_ZASOBY.md) zastępuje
historyczne zarządzanie samymi targetami. Plik w repo nie dowodzi instalacji,
gotowości ani zgody operatora na ruch.

1. Odczytaj `/svc`, `/api/logic/features`, `/api/services/graph` i stan bezpieczeństwa.
2. Uruchom `scripts/systemd-sync.sh`, aby przejrzeć plan bez zmian.
3. Po przeglądzie zastosuj linki: `sudo scripts/systemd-sync.sh --apply`.
   Skrypt zapisze backup/manifest i wykona daemon-reload bez zmiany procesów.
4. Konsolidacja właścicieli rozruchu wymaga osobnej decyzji `--consolidate-boot`.
   Zachowaj sieć/SSH, boot/splash/LCD i ręczny Jupyter.
5. Odczytaj rzeczywiste LoadState/ActiveState/SubState/UnitFileState i członków zadania.
   Brakujące S6/S7/S10 pozostają niedostępne do instalacji i potwierdzenia odczytem.
6. Zadania uruchamiaj/zatrzymuj przez API. Opcjonalne targety są znacznikami.
   Nie aktywuj S1/S3/S4/S9 jako automatycznej kontroli migracji.

S6 jest pasywny. S7 wybiera lokalną wizję ALBO PC. S5/S10 wybiera potrzebną domenę.
S11 uruchamia jedno narzędzie, bez GUI, legacy face i autostartu Jupyter.
Nieznane opcje są odrzucane; błędny krok nie kończy się optymistycznym sukcesem.

Automatyczna weryfikacja używa atrap systemd/zasobów/BUS. Fizyczne sprawdzenie
kamery jest osobnym testem sprzętowym. Próby aktuatorów wykonuje się wyłącznie
ręcznie, po wyraźnej zgodzie operatora dla konkretnego planu. Zgoda na kamerę,
migrację czy wdrożenie nie oznacza zgody na ruch.

Rollback korzysta ze ścieżki kopii wypisanej przez apply:
`sudo scripts/systemd-sync.sh --rollback /etc/systemd/system/_rider_catalog_<znacznik>`.
Jednostki zmienione po migracji nie są nadpisywane po cichu.
