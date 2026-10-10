# Wdrożenie Pi i odtwarzanie

Urządzenie ma własne repozytorium Git i konfigurację lokalną. Kod aktualizujemy
przez Git po SSH; kopiowanie całego workspace WSL nie jest procedurą wdrożenia.
Przed użyciem katalogu repo potwierdź jego ścieżkę w unicie usługi.
`main` w WSL, `main` na GitHubie i kod uruchomiony na Pi mogą mieć różne rewizje.

## Dwie ścieżki

| Ścieżka | Kolejność | Zastosowanie |
| --- | --- | --- |
| Krótka | lokalna zmiana i commit → podgląd na Pi → test funkcji | drobne poprawki i iteracje ze sprzętem przed publikacją |
| Wydanie | push → PR → kontrole i review → merge → aktualizacja Pi | utrwalenie zaakceptowanego kodu na GitHubie i urządzeniu |

Kod tworzymy w WSL na gałęzi roboczej. Kontrolę w WSL dobieramy do zmiany;
pełny zestaw testów nie jest warunkiem każdej krótkiej iteracji. Wynik sprzętowy
potwierdzamy na Pi. Narzędzie `scripts/dev_pi-deploy.py` używa istniejących
Git, SSH i biblioteki standardowej Pythona. Czyta lokalny `evn.ssh.local`
z uprawnieniami `600`; hasło nie trafia do argumentów procesu ani do paczki.

## Krótka ścieżka: podgląd i test na Pi

Przed pierwszym podglądem `main` robota i baza lokalnej gałęzi muszą wskazywać
ten sam commit. W WSL zapisz wybrane zmiany w lokalnym commicie; nie wymaga to
push ani PR. Przykład z katalogu Rider-Pi:

```bash
git switch -c codex/krotki-opis
# edycja; ewentualna krótka kontrola lub powiązany test w WSL
git add <jawnie-wybrane-pliki>
git commit -m "fix(scope): opis zmiany"
make pi-preview
make pi-preview-status
```

Podgląd przesyła przyrost Git przez SSH, sprawdza składnię zmienionego Pythona
na interpreterze urządzenia i przełącza Pi na `rider-preview/<hash>`.
Poprzedni `main` pozostaje punktem powrotu. Każda kolejna poprawka to nowy
lokalny commit i ponowne `make pi-preview`. Nie wykonuj `git pull` w podglądzie.
Hash i gałąź identyfikują cały testowany zestaw; metadane stopki mają cache 60 s.

Po zmianie backendu API użyj:

```bash
make pi-preview PI_DEPLOY_ARGS='--restart-api'
```

Ta opcja restartuje tylko `rider-api.service` i sprawdza HTTP health.
Statyczny web wymaga odświeżenia przeglądarki. Dla innej usługi aplikacyjnej
restart i test dobierz do zmienionego komponentu. Podgląd nie zastępuje
sprawdzenia funkcji na sprzęcie. Nie uruchamiaj równolegle drugiego procesu
korzystającego z tego samego UART, LCD, kamery lub audio.

Powrót do poprzedniego `main`:

```bash
make pi-rollback
```

Wycofanie przywraca zapisany commit; jeśli podgląd restartował API, wycofanie
także restartuje API i sprawdza health. Gałęzie podglądu zachowują historię.
Brudne repo, nadpisanie pliku lokalnego lub zmiana oczekiwanego stanu zatrzymują
operację. Wcześniejsze prace zachowaj zamiast resetować.

## Wydanie: PR, merge i aktualizacja Pi

Po zaakceptowaniu funkcji na Pi opublikuj gałąź, utwórz PR i przeprowadź
powiązane kontrole oraz review. Poprawkę z review sprawdź ponownie w podglądzie,
jeżeli zmienia testowany kod. Po merge użyj pełnego hasha `main`:

```bash
git switch main
git pull --ff-only origin main
make pi-release PI_COMMIT=<pełny-hash-main-po-merge>
make pi-preview-status
```

Narzędzie pobiera `origin/main` na Pi, sprawdza oczekiwany hash i aktualizuje
`main` tylko przez fast-forward. Aktywny podgląd musi mieć identyczne drzewo
plików jak wydanie; squash może zmienić hash commitu. Przy różnicy plików
potrzebny jest nowy podgląd. Bez aktywnego podglądu można wdrożyć zrecenzowany
`main` bezpośrednio. Poprzednią rewizję zapisuje `.git/rider-last-release.json`.
Przy zmianie API dodaj `PI_DEPLOY_ARGS='--restart-api'`; opcja jest dziedziczona
także z aktywnego podglądu.

Porównaj Git, `/api/status/version` i `/healthz`, następnie sprawdź zmienioną
funkcję. Panel działa na `8080`, bridge ruchu na `8081`. Polecenie ruchu nie jest
kontrolą wdrożenia weba. Dla kodu Rider-PC uruchamiaj jego panel w WSL
z istniejącego środowiska (`make start-dev` w repo Rider-PC) i testuj integrację
z Pi; pakiety i modele PC pozostają w środowisku PC.

Obie ścieżki zachowują konfigurację lokalną, runtime i orientację ekranu opisaną
w [architekturze](ARCHITECTURE.md#fizyczna-orientacja-lcd).
Narzędzie odrzuca prywatne env, `config/local/`, dane runtime i lokalne notatki,
również gdy wystąpiły we wcześniejszym commicie paczki i potem zostały usunięte.
Unity systemd, sterowniki, boot i zależności mają osobny zakres wdrożenia.
Nie używaj `systemd-sync.sh` ani `run_boot` przy aktualizacji panelu.

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

`make pi-rollback` dotyczy aktywnego podglądu. Po wydaniu poprzedni commit
odczytaj na Pi z `.git/rider-last-release.json`. W czystym repo wróć do niego
przez `git switch --detach <poprzedni-hash>` i ponów restart wyłącznie zmienionej
usługi oraz jej kontrolę. Oryginalny `main` z wydaniem pozostaje w Git;
kolejny przyrost rozpocznij po świadomym ustaleniu nowej bazy.

Po globalnej awarii najpierw instalujemy obraz Linuxa producenta, następnie
repozytorium, wymagane pakiety i konfigurację lokalną. Kopia 1:1 starego
systemu nie jest wymagana. Biblioteki sprzętu, przypisania pinów i elementy
rozruchu obrazu producenta pozostają punktem odniesienia; sprawdź je przed
uruchomieniem aplikacji. Inwentaryzację i wyniki odtwarzania zapisuj w lokalnych
notatkach operacyjnych, bez sekretów.

Zobacz [development](development.md), [mapowanie systemd](SYSTEMD_SERVICES_MAPPING.md)
i [politykę konfiguracji](config/POLICY.md).
