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

## Podgląd na urządzeniu przed publikacją

Zmiany można najpierw sprawdzić na robocie jako lokalny zestaw plików.
Zapisz bazowy commit, listę zmienianych plików i ich sumy SHA-256 oraz kopię
poprzednich wersji tych plików poza repo. Przenoś wyłącznie jawnie wybrane
pliki kodu i unitów; konfiguracja prywatna i katalogi operacyjne pozostają lokalne.
Przed podmianą potwierdź czysty katalog roboczy i zgodność plików z bazą.
Sprawdź składnię na Pythonie urządzenia oraz definicje przez `systemd-analyze verify`.

Repo urządzenia będzie zawierać lokalne zmiany; bazowy hash Git nie opisuje
całego uruchomionego zestawu. Nie wykonuj wtedy `git pull`. Po akceptacji
podglądu opublikuj i zrecenzuj ten sam zestaw, sprawdź zgodność sum plików,
wycofaj lokalną podmianę i dopiero zaktualizuj czyste repo przez Git.
Wycofanie przywraca wybrane pliki oraz zapisany stan usług i autostartu.

## Migracja autostartu Jupytera

Po podmianie definicji Jupytera na ręczną sprawdź istniejące linki w targetach.
Dla starego linku potwierdzonego w `multi-user.target.wants`:

```bash
sudo systemctl stop jupyter.service
sudo rm -f /etc/systemd/system/multi-user.target.wants/jupyter.service
sudo systemctl daemon-reload
systemctl show jupyter.service -p ActiveState -p UnitFileState
```

Zachowaj `/etc/systemd/system/jupyter.service` wskazujący plik repo.
`systemctl disable` usuwa również ten link, bo definicja znajduje się poza
ścieżką jednostek systemd. Stan `linked` po usunięciu członkostwa w targetach
jest poprawny: jednostka pozostaje dostępna do ręcznego uruchomienia.
Sprawdź też brak innych linków `.wants`/`.requires`, brak startu w sprzątaniu
producenta i brak zależności w DEV. Nie usuwaj ani nie odinstalowuj Jupyter Lab.

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
