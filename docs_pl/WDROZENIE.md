# Wdrożenie Pi i odtwarzanie

Urządzenie ma własne repozytorium Git i konfigurację lokalną. Kod aktualizujemy
przez Git po SSH; kopiowanie całego workspace WSL nie jest procedurą wdrożenia.
Przed użyciem katalogu repo potwierdź jego ścieżkę w unicie usługi.
`main` w WSL, `main` na GitHubie i kod uruchomiony na Pi mogą mieć różne rewizje.

## Aktualizacja aplikacji

Zaloguj się na host i użytkownika z konfiguracji lokalnej. Nie wpisuj hasła
w poleceniu. W repozytorium urządzenia:

```bash
git status --short --branch
git rev-parse HEAD
git fetch origin main
git log --oneline HEAD..origin/main
git diff --stat HEAD..origin/main
```

Poprzednią rewizję zapisz lokalnie. Kontynuuj przy czystym `main`, po przeglądzie
zmian i potwierdzeniu zgodności z Pythonem oraz zależnościami urządzenia.
Wcześniejsze prace zachowaj zamiast resetować.

```bash
git pull --ff-only origin main
```

Przy zmianie backendu restartuj wyłącznie jego usługę aplikacyjną:

```bash
sudo systemctl restart rider-api.service
systemctl status rider-api.service --no-pager
curl --max-time 5 http://127.0.0.1:8080/healthz
curl --max-time 5 http://127.0.0.1:8080/api/status/version
```

Porównaj wersję z commitem repozytorium. Otwórz `/system/` i `/control`, sprawdź
żądania sieciowe oraz błędy przeglądarki. Zmiany statycznego weba zwykle wymagają
odświeżenia przeglądarki; sama dokumentacja nie wymaga restartu usługi.
Bridge ruchu na `8081` jest osobny od panelu na `8080`.
Nie używaj polecenia ruchu jako kontroli wdrożenia weba.

Aktualizacja aplikacji nie obejmuje targetów rozruchu, skryptów producenta,
ustawień sieci/SSH/getty, startu grafiki ani zbiorczej synchronizacji systemd.
Nie uruchamiaj `systemd-sync.sh` ani `run_boot` przy aktualizacji panelu.
Zmiany unitów i zależności wymagają osobnego zakresu wdrożenia i przeglądu.

## Odtwarzanie

Przy awarii aplikacji korzystaj z zapisanej poprzedniej rewizji i przejrzyj
różnice przed zmianą wersji. Zachowaj konfigurację oraz lokalne zmiany
urządzenia, następnie powtórz kontrole usługi. Błąd weba nie wymaga zbiorczego
resetu ani reinstalacji systemu.

Po globalnej awarii najpierw instalujemy obraz Linuxa producenta, następnie
repozytorium, wymagane pakiety i konfigurację lokalną. Kopia 1:1 starego
systemu nie jest wymagana. Biblioteki sprzętu, przypisania pinów i elementy
rozruchu obrazu producenta pozostają punktem odniesienia; sprawdź je przed
uruchomieniem aplikacji. Inwentaryzację i wyniki odtwarzania zapisuj w lokalnych
notatkach operacyjnych, bez sekretów.

Zobacz [development](development.md), [mapowanie systemd](SYSTEMD_SERVICES_MAPPING.md)
i [politykę konfiguracji](config/POLICY.md).
