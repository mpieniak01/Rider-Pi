# Polecenia z rozmowy Venoma

Opcja rozmów jest włączana po stronie Venoma. Pi zachowuje kalibrację,
wykonawcę ruchu oraz decyzję operatora o uzbrojeniu. Agent nie może uzbroić
robota, kasować E-Stop, uruchamiać hold ani zmieniać wysokości, balansu czy akcji.

## Jeden skalibrowany impuls

`GET /api/control/agent/state` zwraca `rider.safety` v1, w tym
`safety.agent_epoch`, `agent_last_seq`, aktywne źródło i pozostały czas
pierwszeństwa sterowania ręcznego.

`POST /api/control/agent/pulse` wymaga prywatnego Bearer `RIDER_AGENT_TOKEN`.
Ciało zawiera dokładnie: `generation`, `agent_epoch`, `seq`, `ts`, `ttl_ms`,
`settings_revision`, `request_id`, `intent_id`, `channel`, `direction`.
Kanał to `chat` albo `voice`; kierunek to `forward`, `backward`, `left`, `right`.

Pi wytwarza `source=agent`, `execution_context=agent` i pojedynczy impuls
`device_settings=true`. Siła i czas pochodzą z bieżącej kalibracji Pi;
maksymalny czas wynosi 1 s. Nie przyjmuje od agenta `vx`, `yaw` ani czasu ruchu.
Token jest także kluczem podpisu HMAC canonical JSON na lokalnym BUS.
Wykonawca sprawdza podpis przed zastosowaniem nastaw. Token i podpis nie są
zwracane w stanie ani ACK.

Ruch wymaga istniejącego operator ARM (`panel`, `manual`, `operator`). Sesja
testowa nie uprawnia agenta. Każde zaakceptowane sterowanie ręczne zmienia
`agent_epoch`; aktywny manual i dodatkowe 0,5 s pierwszeństwa blokują agenta.
Agent ma niezależną sekwencję. Stara odmowa nie zatrzymuje nowego manual ani
nie rozbraja robota. Host zachowuje epoch od początku zamiaru; nie odświeża go
po anulowaniu i nie ponawia POST po nieznanym wyniku.

Publiczny `/api/control` odrzuca agentów. STOP pozostaje dostępny przez
`POST /api/stop` z rzeczywistym `source=agent`, `execution_context=agent`.
Anulowanie starej rozmowy nie wysyła automatycznie globalnego STOP.
ACK SDK nadal nie potwierdza fizycznego wykonania ruchu.

## Gotowy dźwięk

`POST /api/voice/playback` przyjmuje binarny `audio/wav`, ten sam prywatny
Bearer oraz `X-Rider-Playback-Id` (1–64 znaki identyfikatora) i
`X-Rider-Playback-TTL-Ms` (1–60000 ms pozostałego budżetu). Limity: 2 MiB,
mono PCM16, 8–48 kHz, do 15 s. Nie uruchamia lokalnej syntezy.

Koperta to `rider.audio` v1. HTTP 200 i `state=played` oznaczają powodzenie
programu odtwarzającego, a nie pomiar tego, co usłyszał operator. Jest jeden
player, bez kolejki, z blokadą współdzieloną przez API, CLI i voice. Ponowne
przesłanie udanego identyfikatora zwraca wynik bez ponownego odtwarzania.

Podczas odtwarzania voice zamyka mikrofon i odrzuca całą zbieraną wypowiedź,
włącznie z buforem sprzed wykrycia dźwięku. Stan i generacja pochodzą z tej
samej blokady playera; wykrywany jest także krótki dźwięk między ramkami
mikrofonu. Po zakończeniu odtwarzania mikrofon czeka jeszcze 350 ms, a potem
otwiera nowy odczyt. Własny głos robota nie może wrócić jako polecenie rozmowy.
Nie zmienia to uzbrojenia ani sterowania ręcznego.

`POST /api/voice/playback/cancel` przyjmuje `{playback_id}` i wymaga Bearer.
Anulowanie przed końcem uploadu blokuje późny start. Anulowanie/OFF zatrzymuje
player i zamyka uchwyty. Nie zmienia ARM. Zajęty player daje 429, brak playera
503, anulowanie lub wygaśnięcie 409.

## Głos Pi

`text.respond` pozostaje zadaniem tekstowym R2. Voice wybiera opcjonalne
`conversation.respond` tylko wtedy, gdy występuje w `selected.tasks` oraz
aktualna capability mówi `available=true`. Zadanie jest przyjmowane tylko dla
klienta `voice`. Reszta STT/TTS pozostaje wspólna. Hostowe
`data.speech_played=true` pomija ponowną syntezę i odtwarzanie tej samej odpowiedzi.

## Konfiguracja i testy

`RIDER_AGENT_TOKEN` pozostaje wyłącznie w prywatnym środowisku Pi i modułu.
API i motion-executor wczytują opcjonalny `/etc/default/rider-compute`.
Nie zapisujemy tokenu w repozytorium, URL, BUS ani logach.

Testy programowe: `test_agent_motion_contract.py`, `test_audio_playback_api.py`
oraz testy compute/voice używają atrap. Testy sprzętu, zwłaszcza fizycznego
ruchu, są osobnym odbiorem wymagającym zgody operatora.
