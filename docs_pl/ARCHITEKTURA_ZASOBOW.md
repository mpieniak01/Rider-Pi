# Wspólna obsługa zasobów i celów robota

## Wejścia i odpowiedzialność

Panel, API, CLI i aliasy Makefile używają tego samego katalogu
`common/service_catalog.py` oraz kodu wykonawczego. W API działa jedna instancja
`FeatureManager`. CLI domyślnie przesyła polecenia do niej przez HTTP.

Awaryjne `--direct` uruchamia lokalnie **te same handlery i kontrakty**, bez serwera
HTTP, subskrybentów ani dodatkowego demona. Używaj go na Pi, gdy API jest
zatrzymane. Nie uruchamiaj dwóch niezależnych trybów sterowania równolegle.
Dziennik celów jest wspólny; po powrocie API odczytuje zweryfikowaną własność
pasywnych usług. Tryb bezpośredni nie omija zgód na ruch ani kontroli zasobów.

| Element | Jedno źródło |
| --- | --- |
| Cele, aliasy, jednostki, zależności | `common/service_catalog.py` |
| Start, stop, współdzielenie, cofnięcie nieudanego startu | `services/core/features.py` |
| Uruchomienie systemd | `scripts/service-systemd-backend.sh` |
| Właściciel kamery i zamknięcie backendu | `apps/camera/utils.py` |
| Aktywność kamery: cel / proces / świeże klatki | `services/core/camera_state.py` |
| Konfiguracja płytki LCD | `drivers/lcd/board.py` |
| Właściciel LCD, prezentacja i zwolnienie SPI | `apps/ui/lcd_sink.py` |
| Wygaszenie wolnego LCD | `apps/ui/lcd_power.py` |
| Buźka i zdarzenia emocji | `services/api_core/face_anim.py` |
| LED ACT/PWR przez sysfs | `drivers/led.py` |
| UART, aktuatory i telemetria | istniejący wykonawca ruchu |

Prywatne backendy wywołuje wspólny kontroler. Nie są alternatywnym publicznym
sposobem zarządzania celami. Ekran startowy korzysta z tego samego backendu LCD
przed dostępnością HTTP. Narzędzia `dev_*` do diagnostyki sprzętu pozostają
narzędziami ręcznymi; nie należą do zwykłego startu strategii.

## Cel jednym przyciskiem

Wybierz cel i jego wariant w „Zadania i sterowanie”. Jeden przycisk uruchamia
wymagany pakiet lub kończy cel. Koniec celu zwalnia tylko usługi należące do
orkiestratora, które nie mają innych konsumentów. Usługi bazowe pozostają aktywne.
Administrator nadal widzi atomowe jednostki w widoku systemu.

Uzbrojenie pozostaje osobną globalną decyzją operatora. Cel pasywny, buźka,
kamera ani odczyt panelu nie uzbrajają robota. Testy sprzętowe mogące wywołać
ruch nadal wymagają oddzielnej zgody.

Dziennik zapisuje identyfikator startu Linux, PID i czas uruchomienia jednostki.
Po restarcie API odtwarza wyłącznie pasywne cele z pasującymi procesami.
Nie odtwarza zamiaru ruchu ani uzbrojenia. Niezgodna lub stara własność jest
zewnętrzna; STOP celu nie potwierdza wtedy zatrzymania obcych procesów.
Awaryjne zatrzymanie konkretnej jednostki wykonuj jawnie przez jej alias usługowy.

## CLI

Z katalogu projektu, z istniejącym interpreterem runtime:

```bash
python3 scripts/robot_ctl.py status
python3 scripts/robot_ctl.py start s2_camera_preview
python3 scripts/robot_ctl.py stop s2_camera_preview
python3 scripts/robot_ctl.py start s2_camera_preview --seconds 30
python3 scripts/resource_ctl.py lcd off
python3 scripts/resource_ctl.py service status camera-capture@raw.service
python3 scripts/resource_ctl.py service stop camera-capture@raw.service --direct
python3 scripts/robot_ctl.py stop s2_camera_preview --direct
python3 scripts/sys_led-control.py off --direct
make preview-on
make lcd-off CONTROL_MODE=--direct
```

`RIDER_API_URL` / `--url` wybiera serwujące API. `--direct` działa lokalnie,
bez `--url`. Ruchomy start CLI wymaga TTY i oryginalnej koperty operatora
w `--control-file`; nie generuje nowego czasu, TTL ani zgody.
`--seconds` dotyczy wyłącznie nowej, pasywnej sesji.

`sys_control.sh`, `sys_lcd-control.py`, `sys_camera-preview.sh`,
`sys_camera-kill.sh`, `sys_kill-cam.sh` oraz `sys_vision-control.sh`
są aliasami. Zachowane nazwy „kill”, „hard” i „reset” nie oznaczają masowego
zabijania procesów, zmiany GPIO ani resetu płytki. LCD reset/hard prowadzą do
wspólnego on/off; kamera „kill” próbuje zakończyć jej właścicieli usługowych.

## LCD, kamera, LED i oszczędzanie

LCD ma kompensację 270°, BCM BL=0, RST=27, DC=25 dla tej płytki CM4.
Konfiguracja `FACE_LCD_*` pochodzi z jednego modułu. Zmiana obrotu obrazu
kamery `PREVIEW_ROT` nie zmienia montażu LCD.
Blokada plikowa `RIDER_LCD_OWNER_LOCK` (domyślnie
`/tmp/rider-lcd-owner.lock`) chroni przed równoległymi instancjami wspólnego
renderera. Odczyt właścicieli wykrywa także procesy producenta, które jej nie używają.

RAW/EDGE/SSD mają jeden zamykany uchwyt kamery. Restart backendu zamyka
poprzedni uchwyt. Stop i błąd zamykają kamerę; Picamera2 wykonuje stop i close,
V4L2 release. Capture działa domyślnie bez LCD; `DISABLE_LCD=0` jawnie włącza
opcjonalny podgląd przez wspólny renderer. `NO_DRAW=1` nie otwiera LCD.
Stop kamery działającej bez LCD nie zmienia zasilania LCD.

Buźka jest na żądanie. `/face/play`, Studio i legacy LCD render delegują do
tego samego runtime. Zdarzenia `mood`, `listening`, `waiting`, `gesture`
i `audio` są punktem integracji przyszłego czatu. Nie dodajemy klienta GPT
ani kolejnego procesu. W trybie baterii zachowany jest limit FPS i wygaszenie
po bezczynności; tryb kabla jest jawnym ustawieniem. Lokalny CLI play działa
na pierwszym planie, z czasem 1–300 s i sprzątaniem przy zakończeniu.

LED ACT/PWR, podświetlenie LCD i RGB sterownika robota są różnymi urządzeniami.
LED sysfs ma osobny backend; status odczytuje aktywny trigger w nawiasach.
Miganie używa timera Linux. CLI blink pozostaje na pierwszym planie i przy
Ctrl+C/SIGTERM wyłącza własną sesję; nowsze polecenie chroni generacja zapisana
w `RIDER_LED_STATE_PATH` (domyślnie `/run/rider-motion/led_state.json`).

Sniffer pozostaje wyłączony domyślnie; patrz [diagnostyka UART](uart-sniffer.md).
Brak świeżych klatek nie dowodzi wyłączenia kamery. Przyjęcie zapisu GPIO/SPI
nie stanowi pomiaru poboru energii ani potwierdzenia fizycznego wygaszenia.

## Dostarczenie

Aktualizuj cały przyrost wraz z prywatnymi backendami; nie kopiuj pojedynczego
publicznego aliasu. Runtime potrzebuje istniejących uprawnień do sudo bez pytania
dla kontrolowanych backendów i zapisu dziennika. Ograniczone sudoers wymagają
uwzględnienia nowej ścieżki `service-systemd-backend.sh`; nie poszerzaj ich
do dowolnych poleceń. Nie wykonuj przy tym zbiorczej synchronizacji systemd.

Przed publikacją: pełna regresja WSL, następnie podgląd na Pi i potwierdzenie
kamery, istniejącego ekranu startowego, orientacji oraz wygaszenia. Próby ruchu
pozostają osobne. Samo przejście testów z atrapami nie potwierdza zachowania sprzętu.

## Podgląd tego zakresu

```bash
python3 scripts/dev_pi-deploy.py preview --resource-scope --restart-api
```

Flaga dopuszcza wyłącznie ustaloną listę backendów LCD/LED i aliasów. Kamera musi
być nieaktywna. Narzędzie zamyka stare procesy API/LCD przed zmianą kodu,
przywraca poprzednio aktywny ekran i zapisuje tę samą procedurę dla rollbacku.
Wykonawca ruchu nie jest restartowany przez tę flagę.

LED AUTO korzysta z domyślnego triggera device tree lub pierwszego rzeczywiście
odczytanego triggera przed ręcznym sterowaniem w bieżącym starcie Linux.
Nie zgaduje wartości. Ostatnia świeża klatka po STOP nie potwierdza działającej kamery.


## Statusy urządzeń

Kamera i LCD prezentują ON / OFF. Nieznany oznacza brak dostępnej obserwacji,
błąd jej odczytu lub brak połączenia z API. Brak świeżej klatki nie oznacza OFF.
Kamera wymaga obserwacji usług i zajęcia zasobu; /healthz, /state, katalog i
/api/resource/camera używają wspólnej projekcji. LCD czyta wyłącznie istniejący
poziom wyjścia GPIO podświetlenia: confirmation=gpio_level_observed,
status_basis=backlight_gpio. Nie konfiguruje pinu ani nie wysyła poleceń SPI.
Odczyt działa po restarcie API; nie jest pomiarem prądu ani potwierdzeniem
pracy matrycy. Ostatnie potwierdzenia renderera/klatek pozostają diagnostyką.
Obserwacje buforowane maksymalnie 3 s, unieważniane po sterowaniu zasobem.
Cache nie jest używany do zezwalania na ruch ani przejęcia sprzętu.
