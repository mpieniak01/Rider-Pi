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
| ARMED | Jawny plan i owner; panel operatora bez timera, testy/nawigacja z ograniczonym lease |
| ESTOP | Zatrzaśnięta blokada; osobny clear pozostawia DISARMED |
| UNKNOWN | Brak świeżego snapshotu; klient blokuje sterowanie |

ARM/clear wymagają operator_consent=true, niepustego operator_plan i oryginalnej
koperty. Owner: manual/follow_me/navigation. Aktuatory wymagają request_id,
source, generation, rosnącego seq, ts oraz ttl_ms 1–500. API i wykonawca
walidują niezależnie. Klient korzysta z server_time API; nie odświeża starego
żądania. Jazda/obrót: [-1,1]. Impuls panelu z device_settings korzysta z
deskryptora (0.01–0.5 s). Maksimum pojedynczego impulsu wynosi 500 ms również
dla poleceń ogólnych i nawigacji; zakres konfiguracji nawigacji to 50–500 ms.
Maksymalna wartość prędkości to 1.0. Prędkość/impuls manuala ogranicza dodatkowo
zapisany profil kierunku; ograniczona świeżą decyzją nawigacja korzysta z własnej
polityki, bez dziedziczenia wartości impulsu i maksimum kierunku manualnego.
Rampy pozostają wspólne. Decyzja nawigacji jest ważna najwyżej 500 ms i nigdy
poza pozostałym budżetem od przechwycenia obrazu; wygaśnięcie nadal zatrzymuje ruch.
Zwiększenie zakresów nie zmienia zapisanych wartości ani nie udziela zgody na ruch.
STOP/disarm/E-Stop nie wymagają
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

Zobacz [jakość programu i otwartą listę ręcznych pomiarów](physical-motion.md)
oraz [kontrakt odometrii/odniesienia](odometry.md). IMU/bateria zachowują oryginalne
czasy osobnych odczytów. Brak/stare dane blokują ARM i rozbrajają aktywny ruch
przez tę samą bramę; nie wymyślamy fizycznych progów baterii/przechylenia.
Świeże MOVE=0 jest natychmiast potwierdzoną pauzą. Koniec impulsu panelu
zachowuje uzbrojenie; wygaśnięcie sesji czasowej i błędy danych/intencji
unieważniają zgodę.

Parser odpowiedzi SDK używa monotonicznego deadline i dopasowuje adres/długość/
sumę kontrolną. Odczyt/zapis serial mają ograniczony czas na tym jednym obiekcie.
Protokół nie ma ID transakcji: dwóch spóźnionych identycznych adresów/długości
nie można odróżnić. Typ odpowiedzi zachowujemy, bez zgadywania jego reguły.
Opóźnienie transportu i mechaniczne zatrzymanie nadal wymagają pomiaru operatora.

Regulator ma dt, rampę i termin krótkiego celu. Safety STOP zeruje cel natychmiast.
Znormalizowane wartości nie mierzą m/s ani drogi hamowania.
Awaria UART/SDK lub niepotwierdzony STOP blokuje readiness i nowy ARM; potrzebny
jest nowy sprawny wykonawca. SDK źródłowo potwierdza zerowanie prędkości.
Wysokość i balans korzystają z ogłoszonych możliwości pozycji/trybu;
stop_verified=false nie potwierdza fizycznego przerwania. Figury producenta
pozostają zablokowane do charakterystyki przerwania. SIGTERM uruchamia cleanup; SIGKILL, utrata UART/zasilania
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

## Wspólne ustawienia urządzenia

Nastawy ruchu i panel kalibracji korzystają z [kontraktu ustawień Pi](calibration.md).
Polecenia chronione zawierają settings_revision; strzałki wysyłają kierunek
i device_settings=true. Uzbrojenie operatora trwa między impulsami. Koniec
impulsu zatrzymuje bez rozbrojenia; błędy i STOP nadal unieważniają sesję.
Zgoda testowa pozostaje oddzielna.

## Warstwy walidacji w kodzie

`executor_admission` wydziela uporządkowane etapy dopuszczenia i wykonania
z `MotionExecutor`: kontrole źródła i ustawień, walidację aktuatora,
autoryzację bramy oraz obsługę STOP i celu. Działają synchronicznie pod tą
samą blokadą wykonawcy; nie tworzą drugiego właściciela UART.
`calibration_schema` zawiera czystą walidację profilu, a `calibration_profiles`
zachowuje publiczne importy oraz operacje zapisu i aktywacji.


## Próby impulsów A/B/C (kontrakt v1)

Wersjonowany katalog apps.motion.trial_profiles definiuje ręczne próby do przodu: A 1×500 ms, B 2×250 ms z przerwą 100 ms, C 5×100 ms z przerwami 100 ms. Siła oraz rampy pochodzą z aktualnych ustawień manualnych. Nastawa czasu kierunku musi odpowiadać recepturze; próba nie omija jej limitu. Zapisany profil bazowy operatora nie jest nadpisywany.

Serię odmierza PulseTrials w istniejącym MotionExecutor, z tą samą bramą, zegarem monotonicznym i rampą. Nie tworzy dodatkowego właściciela UART ani procesu sterowania. Przerwa zaczyna się po zaakceptowaniu zerowego wyjścia; raportuje się faktyczne czasy. Limit całej próby 1500 ms nie jest odnawiany, koperta Startu nadal ma maksymalny TTL 500 ms. Potwierdzenie SDK nie potwierdza fizycznego przemieszczenia lub zatrzymania.

Odczyt katalogu/statusu nie uzbraja i nie porusza robota. POST /api/motion/trials przekazuje jawną zgodę i plan przez standardowy kontrakt arm/manual/panel z trial_profile_id, trial_version 1, settings_revision i panel_id. Wykonawca sprawdza pełną kopertę, stan DISARMED, gotowość i rewizję przed rozpoczęciem. Te same znaczniki w standardowym kanale bezpieczeństwa mają tę samą walidację.

GET /api/motion/trials/profiles i GET /api/motion/trials/<request_id> zwracają kontrakt rider.pulse_trials v1. Status wykonawcy zawiera pulse_trials.current oraz ograniczoną historię. Po normalnym zakończeniu kończy się uprawnienie próby. STOP/E-Stop, nowa generacja, anulowanie lub nowe sterowanie ręczne usuwają całą pozostałą serię; opóźniona odpowiedź nie może jej wznowić. Powtórzony request_id nie wykonuje prób ponownie.

Testy automatyczne korzystają wyłącznie z atrap czasu, adaptera i BUS. Wdrożenie oraz odczyty GET nie są zgodą na fizyczną próbę. Optymalizacja pętli i odczytów usług pozostaje odrębnym zakresem.
