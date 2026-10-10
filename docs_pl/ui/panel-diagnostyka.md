# Panel Pi: diagnostyka i wersja

Flask udostępnia panel na porcie `8080`. `/` i `/view` pokazują przegląd,
`/control` sterowanie robotem, a `/system/` diagnostykę. Administracja usługami
pozostaje w zaawansowanej części sterowania. `/home` jest ekranem Google Feed.
`/home` i `/google_home` są dostępne bezpośrednio, lecz ukryte w bieżącym menu.
Interfejs obsługuje język polski i angielski.

Diagnostyka pokazuje karty usług według komponentów oraz rozwijaną tabelę.
Liczniki rozróżniają usługi nieaktywne i awarie. Powiązania z `SERVICE_META`
opisują komponenty aplikacji, bez deklarowania zależności rozruchowych systemd.
Ekran co pięć sekund odczytuje `GET /api/services/graph`, utrzymując jedno
żądanie naraz i limit dwunastu sekund. Po błędzie zachowuje ostatnie dane
i oznacza je jako nieaktualne. Nie wysyła poleceń ruchu ani zarządzania usługami.

Sekcja **Sieć** przedstawia rzeczywisty stan `wlan0`, niezależnie od statusów usług:
carrier i adres IPv4 oznaczają połączenie w LAN. Odczyt obejmuje blokadę radia,
adresy, trasę domyślną i autostart `dhcpcd`; brak narzędzia lub danych jest stanem
nieznanym, a nie automatycznie awarią połączenia. Nie sprawdzamy w ten sposób Internetu.
Pole `network.wifi` w `/api/services/graph` pochodzi z sysfs oraz odczytów `ip` i systemd
z limitem jednej sekundy. Nie zawiera SSID, hasła ani zawartości konfiguracji sieci.

`wifi-unblock.service` odblokowuje jedynie radio przed konfiguracją sieci; sukces
tej usługi nie potwierdza połączenia Wi-Fi. Na obrazie producenta obsługą `wlan0`
zajmuje się `dhcpcd` i jego hook wpa_supplicant. Nie uruchamiaj równolegle dodatkowej
instancji `wpa_supplicant@wlan0` ani innego menedżera tego interfejsu. Nieaktywny
ConnMan nie wymaga `connman-wait-online`. Wi-Fi konfiguruje się lokalnie na urządzeniu,
bez publikowania plików zawierających hasło. Zasady odblokowania i zachowania stanu:
[rfkill](https://manpages.debian.org/bullseye/rfkill/rfkill.8.en.html),
[systemd-rfkill](https://manpages.debian.org/bullseye/systemd/systemd-rfkill.service.8.en.html).

Stopka odczytuje `GET /api/status/version` po załadowaniu strony. Odpowiedź
zawiera `available`, `branch`, `commit`, `dirty`, `message` i `ts`.
Źródłem jest repozytorium uruchomionego kodu, odczytane poleceniami Git z limitem
jednej sekundy i cache na sześćdziesiąt sekund. Brak danych zwraca HTTP 200
z `available=false`; detached HEAD jest opisany jawnie. Kopiowanie commita
działa też przez fallback schowka przy HTTP w LAN. Na małych ekranach
stopka zawija się i pozostaje w zwykłym układzie dokumentu.

Sprawdzając zmiany, uwzględnij kontrakty API, cztery motywy, różne szerokości
ekranu, oba języki, wolne i błędne odpowiedzi oraz stopkę na każdej stronie.
Wyniki konkretnych audytów zapisuj lokalnie.

![Diagnostyka na komputerze](../../docs/assets/ui/diagnostics-desktop.png)
![Diagnostyka na telefonie](../../docs/assets/ui/diagnostics-mobile.png)
![Stopka wersji na telefonie](../../docs/assets/ui/version-footer-mobile.png)
