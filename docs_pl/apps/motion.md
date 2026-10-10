# Architektura ruchu Rider-Pi

Stan kontraktu bramy v1. SDK ACK nie jest pomiarem fizycznego wykonania.
Zobacz [bezpieczeństwo](safety.md) i [politykę środowisk](../POLITYKA_SRODOWISK.md).

## Ścieżka sterowania

Panel Pi/PC → API :8080 lub opcjonalny HTTP bridge :8081 →
`services.safety_contract` → BUS `motion.command` → `apps.motion.executor`
(brama, regulator, SDK) → UART. Tylko wykonawca posiada UART dla ruchu i odczytów.
Sprawdza lock i rzeczywistego ownera portu; cudzy/nieznany owner oznacza odmowę.
`sensor-reader` projektuje `motion.sensors.raw` na BUS i nie tworzy SDK.
Odczyt panelu korzysta ze snapshotu, błędne dane są null.

Domyślny `XgoAdapter` bez ownera i bramy pozostaje nieaktywny. Guard SDK 1.4.2
blokuje reset/action255 w konstruktorze. Nieznany SDK odmawia startu.
`motion.main` deleguje do wykonawcy; legacy bridge nie steruje SDK.
Passive vision/tracker nie uruchamia jazdy. Follow potrzebuje bieżącego task
intent z katalogu; stary controller nie przejmuje zgody nowej generacji.

## Zgoda i koperta

| Stan | Znaczenie |
| --- | --- |
| DISARMED | Odczyty, brak aktuacji; stan każdego startu |
| ARMED | Konkretny plan, owner i lease do 30 s |
| ESTOP | Zatrzaśnięta blokada; osobny clear pozostawia DISARMED |
| UNKNOWN | Brak świeżego snapshotu; klient blokuje sterowanie |

ARM/clear wymagają operator_consent=true, niepustego operator_plan i oryginalnej
koperty. Owner: manual/follow_me/navigation. Aktuatory wymagają request_id,
source, generation, rosnącego seq, ts oraz ttl_ms 1–500. API i wykonawca
walidują niezależnie. Klient korzysta z server_time API; nie odświeża starego
żądania. Jazda/obrót: [-1,1], impuls do 0,25 s. STOP/disarm/E-Stop nie wymagają
świeżej koperty. STOP zmienia generację i usuwa cel. Nowszy cel zastępuje pending
z terminalnym ACK; polecenia nie wracają po ARM.

## Potwierdzenie

GET /api/control/state i GET /api/safety są tylko odczytem. Polecenia używają POST.
Aktuacja przez GET jest zabroniona; legacy aliasy nie pomijają koperty.
accepted/202 oznacza pending. executed/confirmed oznacza przekazanie SDK;
rejected oznacza odmowę/anulowanie/błąd. physical_completion pozostaje unverified.
Terminalny ACK dopasowuje ID/akcję/source/seq i czas po wysłaniu. Snapshot
zachowuje ograniczoną historię wyników. Historia panelu nie jest kolejką ruchu.
Brak BUS/ACK nie jest sukcesem. Zwolnienie ruchowego zasobu wymaga confirmed STOP.

## Dynamika i granice

Regulator ma dt, rampę i termin krótkiego celu. Safety STOP zeruje cel natychmiast.
Znormalizowane wartości nie mierzą m/s ani drogi hamowania.
Awaria UART/SDK lub niepotwierdzony STOP blokuje readiness i nowy ARM; potrzebny
jest nowy sprawny wykonawca. SDK źródłowo potwierdza zerowanie prędkości.
Height/balance/canned actions pozostają niedostępne do ręcznej charakterystyki
bezpiecznego przerwania. SIGTERM uruchamia cleanup; SIGKILL, utrata UART/zasilania
Pi nie mają fizycznego dowodu STOP. Nie deklarujemy watchdoga firmware.

## Runtime i migracja

Status: /run/rider-motion/status.json; intent: feature_state.json w tym katalogu.
MOTION_STATE_PATH/FEATURE_STATE_PATH służą izolacji. Pliki przeżywają restart,
ale nowa generacja unieważnia zgodę. Producer status jest osobnym <unit>.json.

Zmiana właściciela UART i unitów wymaga osobnego planu i kopii unitów. Zwykły
pi-preview chroni drivers/systemd. W uzgodnionym oknie, bez autonomii, zatrzymaj
starego ownera, zaktualizuj kod/wybrane unity, wykonaj daemon-reload i uruchom
jednego nowego ownera DISARMED. Rollback przywraca zgodny kod i unity.
Migracja nie wykonuje automatycznej próby ruchu. Zachowaj LCD 270°, boot, Wi-Fi i SSH.
