# Rider-Pi Apps — **ARCHITEKTURA**

## Cel i zasady ogólne

- **Niska energia** i **stabilność** — usługi lekkie, restartowalne przez `systemd`.
- **Jedno wejście HTTP**: publiczne API na porcie 8080.
- **Wymiana wewnętrzna**: ZMQ PUB/SUB (5555/5556) + pliki w `data/` i `snapshots/`.
- **Środowisko docelowe**: Raspberry Pi (Debian/Bookworm), **Python 3.9**.

---

## Warstwy i procesy

### 1) Interfejs HTTP

- `` — REST API (port **8080**).
  - Ekspozycja zdrowia (`/healthz`), sterowanie (`/api/control`), chat, statusy, serwowanie assetów z `data/`, `snapshots/`.
  - Proxy do wewnętrznych usług przez bus (ZMQ) i/lub wywołania lokalne.

### 2) Ruch / Mostek Web

- `` (port **8081**) — uproszczony interface www → ruch (opcjonalny).
- **Motion Bridge** — jedyny komponent z dostępem do **UART **`` (sterowanie aktuatorami).
  - Odbiera komendy z busa (np. `motion.move`, `motion.stop`), publikuje telemetrię `motion.state`.

### 3) Wizja / Kamera

- **Vision/Camera** — moduły w `apps/camera/*` i `apps/vision/*`.
  - Źródło obrazu (libcamera), detektory (HOG/SSD/TFLite).
  - Wyniki zapisują do `snapshots/` / `data/` (ostatnia klatka, surowe ujęcia) i publikują eventy (np. `vision.person`, `vision.obstacle`).

### 4) Navigator (Autonomous Exploration)

- **Navigator** — moduł autonomicznej nawigacji w `apps/navigator/*`.
  - Tryb „Rekonesans" (Stage 1): reaktywne unikanie przeszkód.
  - Subskrybuje `vision.obstacle`, publikuje na `navigator.state`.
  - Dwie strategie: STOP (zatrzymanie) i AVOID (omijanie).
  - Sterowanie przez API: `/api/navigator/start`, `/api/navigator/stop`, `/api/navigator/config`.
  - Integracja z interfejsem webowym w `control.html`.
  - Zobacz: `docs/modules/navigator.md`

### 5) Głos / Chat

- **Voice** — modułowa architektura głosowa w `apps/voice/` obsługująca dwa tryby pracy:
  - **Tryb plikowy** (`file`): klasyczny pipeline capture→ASR→Chat→TTS→playback
  - **Tryb strumieniowy** (`realtime`): WebSocket duplex z partial ASR, streaming chat/TTS
  - **Komponenty kluczowe**:
    - `svc_core.py` — wybór trybu (file/stream) i delegacja do odpowiedniego serwisu
    - `svc_file.py` — implementacja trybu plikowego
    - `svc_stream_runner.py` — wrappery CLI dla trybu strumieniowego
    - `stream/svc_streaming.py` — główny serwis strumieniowy (StreamingVoiceService)
    - `stream/transport.py` — transport WebSocket z auto-reconnect
    - `stream/state.py` — maszyna stanów PTT (Push-To-Talk)
    - `stream/handlers.py` — obsługa wiadomości/zdarzeń WebSocket
    - `stream/playout.py` — capture audio i playback TTS
    - `audio/capture.py`, `audio/playback.py` — moduły niskopoziomowe ALSA/Pulse
  - Integracja: VAD, KWS, ASR, Chat, TTS; komunikacja przez bus (ZMQ) i socket ``
- **Chat** — integracja przez `/api/chat/*` + wymiana stanów na busie.

> **Szczegółowa dokumentacja**: `docs/modules/voice.md` — pełny opis architektury, konfiguracji, API

### 5) Twarz (Face)

- **UI Face** w `apps/ui/face/*`:
  - **Animator** → **Renderer** (PIL/RAW) → **LCD** (sterownik ILI9xx).
  - Konfiguracja parametrów w `config/face.toml`; szyte ENV `FACE_*`.
  - Najnowsze elementy: usta **„wstążka”**, brwi **arc**, drift+clamp źrenic, **sprzęgło blink→look**.

---

## Porty i gniazda

| Usługa / Kanał               | Protokół | Port / Ścieżka  | Rola                                                   |
| ---------------------------- | -------- | --------------- | ------------------------------------------------------ |
| API                          | HTTP     | **8080**        | Wejście REST (control/chat/healthz, serwowanie plików) |
| Web-Motion Bridge (opcjonal) | HTTP     | **8081**        | Prostszy interfejs do ruchu                            |
| Voice Web API (opcjonalne)   | HTTP     | **8092**        | Lokalny TTS/ASR (Piper/Vosk) przez HTTP                |
| ZMQ PUB/SUB                  | ZMQ      | **5555 / 5556** | Wewnętrzny bus komunikatów                             |
| Voice sock                   | UNIX     | ``              | Komunikacja voice                                      |
| UART                         | Serial   | ``              | Kontrola aktuatorów (wyłącznie przez Motion Bridge)    |

> Domyślnie **brak** bezpośrednich zewnętrznych portów poza 8080/8081.

---

## Przepływy danych (wysoki poziom)

```text
[HTTP Client] ──> (8080) API ─┬─> BUS PUB/SUB (5555/5556) ──> Vision/Voice/Motion/Face
                              ├─> lokalne wywołania modułów
                              └─> serwowanie plików z data/, snapshots/

Vision/Camera ──> snapshots/, data/ (+ eventy na BUS) ──> API/Clients
Motion Bridge  ──(bus)──> UART /dev/ttyAMA0 ──> aktuatory
Voice/Chat     ──(bus + sock)──> odpowiedzi/stan ──> API
Face (Animator→Renderer→LCD) ──> podgląd przez API lub bezpośrednio na LCD
```

**BUS (ZMQ)** — kanały przykładowe:

- `motion.move`, `motion.stop`, `motion.state`
- `vision.face`, `vision.person`, `vision.motion`, `vision.obstacle`
- `voice.state`, `voice.kws`, `voice.vad`
- `face.state`, `face.render`
- `events.sentiment`, `events.nlu.emotion` — zdarzenia dla choreografa
- `command.face.expression` — komendy do twarzy z choreografa
- `navigator.control`, `navigator.state` — autonomiczna nawigacja (Rekonesans)

---

## Katalogi i artefakty

| Katalog / plik | Przeznaczenie                                        |
| -------------- | ---------------------------------------------------- |
| `apps/`        | Moduły aplikacyjne (UI/face, camera, vision, voice…) |
| `services/`    | Warstwa serwisowa (API, mostki, rejestry)            |
| `web/`         | Frontend / assety web                                |
| `config/`      | Konfiguracje                                         |
| `data/`        | Dane pomocnicze/ostatnie pliki (np. `last_frame`)    |
| `snapshots/`   | Zrzuty klatek / surowe ujęcia                        |
| `scripts/`     | Skrypty operacyjne, deweloperskie, diagnostyczne     |
| `drivers/`     | Sterowniki sprzętowe (XGO, LCD)                      |
| `tests/`       | Testy unit/integration                               |

### Historia reorganizacji struktury

**PR #10 (2025-01):** Utworzenie warstwy sterowników `drivers/`
- Przeniesiono sterowniki XGO i LCD z `apps/` do dedykowanego katalogu `drivers/`
- Wprowadzono abstrakcję sprzętową oddzielającą logikę aplikacji od interfejsów sprzętowych
- Zobacz: [docs/_pr_summaries/PR10_SUMMARY.md](docs/_pr_summaries/PR10_SUMMARY.md)

**PR #11 (2025-01):** Wprowadzenie trybu symulacji
- Dodano symulowane implementacje sterowników (`drivers/xgo/sim.py`, `drivers/lcd/sim.py`)
- Wprowadzono fabryki sterowników reagujące na zmienną `RIDER_SIMULATOR`
- Umożliwiono rozwój i testowanie bez dostępu do fizycznego sprzętu
- Zobacz: [docs/_pr_summaries/PR11_SUMMARY.md](docs/_pr_summaries/PR11_SUMMARY.md)

**PR #13 (2025-10):** Konsolidacja skryptów operacyjnych
- Scalono skrypty z katalogów `ops/` i `tools/` do `scripts/`
- Wprowadzono ujednoliconą konwencję nazewnictwa (prefiksy: `sys_`, `diag_`, `dev_`, `demo_`, `util_`)
- Zobacz: [docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md](docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md), [scripts/README.md](scripts/README.md)

---

## Konfiguracja i parametry

- **Źródła konfiguracji**:

  1. **ENV **`` — szybkie kręcenie gałkami (blink, look, drift, sprzęgło, follow).
  2. `` — klucze **lowercase** dla renderera (np. `mouth_y_k`, `brow_y_k`), aliasy `FACE_*` dla zgodności.
  3. Parametry usług (porty, poziomy logów) przez `systemd`/ENV.

- **Reguła**: API i mostki **nie** sięgają bezpośrednio do sprzętu (poza wyspecjalizowanymi driverami). Sprzęt (UART/LCD) jest za dedykowanymi modułami.

---

## Punkty integracji (interfejsy)

### API (HTTP 8080)

- `/healthz` — zdrowie całego systemu.
- `/api/control` — ruch: `{"action":"move|stop|turn", ...}` (walidowane).
- `/api/chat/*` — rozmowa / asysta (przekierowanie do komponentów voice/chat).
- `/files/*` — serwowanie plików z `data/`, `snapshots/` (ostatnie klatki, PNG).

### BUS (ZMQ)

- Wewnętrzny, namespacy jak wyżej. Subskrypcje per usługa.

### LCD / Render

- `apps/ui/face/driver_ili9xx.py` — most do ekranu (RAW/ShowImage).
- `scripts/dev_face-lcd-direct.py` — tryb demo (LCD/PNG).

---

## Sekwencja startu (przykład)

1. `rider-api.service` (HTTP 8080) → gotowy `/healthz`.
2. Broker ZMQ i subskrybenci (Vision/Voice/Motion/Face).
3. Vision/Camera (jeśli włączone) → publikuje eventy, zapisuje klatki.
4. Motion Bridge → nasłuch na busie, dostęp do `/dev/ttyAMA0`.
5. Face → animacje na LCD (jeśli urządzenie obecne).

> Usługi niezależne — restart jednej **nie** powinien blokować pozostałych.

---

## Granice odpowiedzialności i bezpieczeństwo

- **Kontrola ruchu**: tylko przez Motion Bridge; walidacja `action`, limity czasu i częstotliwości.
- **Sprzęt**: UART i LCD wyłącznie przez dedykowane moduły.
- **Dostęp zewnętrzny**: przez API 8080 (reszta lokalnie).
- **Energia**: Vision/Kamera domyślnie wyłączone (aktywowane tylko przy potrzebie).

---

## Diagram (skrót)

```text
           +------------------+              +--------------------+
HTTP 8080  |  rider-api       |<--static----|  data/, snapshots/  |
           |  (REST gateway)  |              +--------------------+
           +----+----+--------+
                |    |
                |    +--------------------------+
                |                               \
                v                                v
        +--------------+  PUB/SUB  +------------------+      +-----------------+
        | MotionBridge |<--------->| Vision/Camera    |      | Voice/Chat      |
        | (/dev/tty*)  |           | (detektory, I/O) |      | (sock, TTS/VAD) |
        +--------------+           +------------------+      +-----------------+
                |
                |                               +-------------------------------+
                +------------------------------>| Face (Animator→Renderer→LCD)  |
                                                +-------------------------------+
```

---

## Moduł Voice — Architektura szczegółowa

### Struktura modułu (`apps/voice/`)

Moduł voice został zrefaktoryzowany (PR#1–PR#4, 2024) w celu uproszczenia i modularyzacji. Obecna architektura wspiera dwa tryby pracy z elastycznym wyborem transportu.

#### Tryby pracy

1. **Tryb plikowy (`file`)** — klasyczny pipeline:
   - Capture → plik WAV → ASR → Chat (text) → TTS → playback
   - Niskie zużycie zasobów, wysoka kompatybilność
   - Brak partial results, pełna transkrypcja po zakończeniu nagrania

2. **Tryb strumieniowy (`realtime`)** — WebSocket duplex:
   - Audio chunks (20ms) → WebSocket → partial ASR + streaming Chat/TTS
   - Barge-in (przerwanie TTS przez nową mowę)
   - Auto-reconnect z exponential backoff
   - Wymagany backend obsługujący realtime (np. OpenAI Realtime API)

#### Komponenty kluczowe

**Wybór trybu i delegacja:**
- `svc_core.py` — funkcje `run_listen()`, `run_once()`, `run_ptt()`
  - Analizuje konfigurację `transport` w sekcjach `[asr]`, `[chat]`, `[tts]`
  - Deleguje do `svc_file.py` (tryb file) lub `svc_stream_runner.py` (tryb realtime)

**Tryb plikowy:**
- `svc_file.py` — klasa `VoiceService`, funkcje `run_listen_file()`, `run_once_file()`
- Wykorzystuje: `audio/capture.py`, `audio/playback.py`, `asr.py`, `chat.py`, `tts.py`

**Tryb strumieniowy:**
- `svc_stream_runner.py` — wrappery CLI: `run_listen_stream()`, `run_ptt_stream()`, `run_once_stream()`
- `stream/svc_streaming.py` — `StreamingVoiceService` (główny serwis, 700+ linii)
  - Integruje mixiny: `StreamHandlersMixin`, `StreamPlayoutMixin`
  - Zarządza lifecycle WebSocket, audio queues, worker threads
- `stream/transport.py` — `WebSocketTransport`, `ReconnectingTransport`
  - Obsługa ping/heartbeat, exponential backoff retry
  - Wsparcie dla `websockets` (async) i `websocket-client` (sync fallback)
- `stream/state.py` — `PTTStateMachine` (maszyna stanów Push-To-Talk)
  - Stany: IDLE, LISTENING, SPEAKING, PROCESSING
  - Eventy: PTT_START, PTT_STOP, ASR_PARTIAL, TTS_START, TTS_END
- `stream/handlers.py` — `StreamHandlersMixin`
  - Obsługa wiadomości WebSocket (ASR partial, TTS audio chunks, sesja)
  - Keyboard PTT loop, ding sounds
- `stream/playout.py` — `StreamPlayoutMixin`
  - Audio capture thread (wysyłanie chunków do WebSocket)
  - TTS player thread (odtwarzanie przychodzących audio chunks)
  - Jitter buffer, barge-in handling

**Moduły współdzielone:**
- `audio/capture.py` — przechwytywanie audio (ALSA/Pulse/command)
- `audio/playback.py` — odtwarzanie audio (ALSA/Pulse)
- `audio/alsa.py` — narzędzia ALSA (lista urządzeń, konfiguracja)
- `asr.py` — abstrakcja ASR (OpenAI, Vosk)
- `chat.py` — integracja Chat API (streaming generator)
- `tts.py` — synteza mowy (OpenAI, Piper)
- `vad.py` — Voice Activity Detection
- `kws.py` — Keyword Spotting (hotword detection)

**CLI i API:**
- `cli.py` + `cli_commands.py` — interfejs linii poleceń
- `web.py` — HTTP API (Flask): `/asr`, `/tts`, `/capture`, `/healthz`
- `main.py` — główny entry point (używany przez systemd)

### Przepływ danych

#### Tryb plikowy (file)

```text
1. [Hotword/PTT] → trigger capture
2. audio/capture.py → WAV file (silence detection via VAD)
3. asr.py → transcript (text)
4. chat.py → response (text)
5. tts.py → audio file (WAV/MP3)
6. audio/playback.py → speaker output
7. Powrót do kroku 1 (w trybie listen)
```

**Kluczowe punkty:**
- Jeden plik WAV na capture (zapisywany opcjonalnie dla debugowania)
- ASR dopiero po zakończeniu nagrania (brak partial results)
- Chat zwraca pełną odpowiedź (nie streaming)
- TTS generuje pełny plik audio przed playbackiem

#### Tryb strumieniowy (realtime)

```text
1. [PTT Start] → WebSocket session.create
2. Capture thread → audio chunks (20ms PCM16) → WebSocket send
3. WebSocket recv → partial ASR transcript → UI update
4. [Silence detection] → audio.commit → finalna transkrypcja
5. WebSocket recv → streaming Chat response (tekst) → sentence buffering
6. Sentence complete → TTS start → audio chunks PCM16
7. TTS player thread → audio chunks → jitter buffer → playback
8. [Barge-in] → stop TTS, przerwij playback, nowa tura (krok 2)
9. [PTT Stop] → session cleanup, powrót do IDLE
```

**Kluczowe punkty:**
- Duplex audio: równoczesne wysyłanie capture i odbieranie TTS
- Partial ASR publikowane na bieżąco (UI updates)
- Streaming Chat: odpowiedź generowana jako async generator
- Sentence buffering: TTS czeka na `.`, `!`, `?` przed syntezą
- Barge-in: detekcja nowej mowy → cancel TTS, clear buffers
- Reconnect: automatyczne wznawianie połączenia po utracie (exponential backoff)

### Konfiguracja trybu

Tryb wybierany automatycznie na podstawie `transport` w konfiguracjach:

```toml
[asr]
backend = "openai"
transport = "realtime"    # file | realtime

[chat]
backend = "openai"
transport = "realtime"

[tts]
backend = "openai"
transport = "realtime"
```

Jeśli **wszystkie** trzy (`asr`, `chat`, `tts`) mają `transport = "realtime"` → tryb strumieniowy.
W przeciwnym razie → tryb plikowy (file).

> **Uwaga:** W przypadku konfiguracji mieszanej (np. tylko jeden z modułów ma `transport = "realtime"`, pozostałe `file`), system przechodzi w tryb plikowy dla wszystkich usług. Tryb częściowo strumieniowy nie jest obsługiwany.
### Historia refaktoryzacji

**PR#1 (Clean & Freeze):**
- Usunięto duplikaty: `ws_transport.py`, `stream_transport.py`
- Pozostawiono `audio/*` do późniejszej migracji

**PR#2 (CLI Unification):**
- Konsolidacja CLI: usunięto odniesienia do nieistniejącego `cli_new.py`
- Jeden spójny moduł `apps.voice.cli`

**PR#3 (Tests Migration & Shim Removal):**
- Migracja testów z legacy shims do nowych modułów
- Usunięto shimmy: `svc_stream.py`, `state.py`, `ptt_state.py`, mixiny
- Nowy moduł: `svc_stream_runner.py` (wrappery dla CLI)

**PR#4 (WebSocket Transport Consolidation):**
- Usunięto duplikat `apps/voice/transport.py`
- Jeden transport: `apps/voice/stream/transport.py`

**PR#5 (Dokumentacja):**
- Aktualizacja `ARCHITECTURE.md` i `docs/modules/voice.md`
- Spójny opis nowej architektury

### Pliki usunięte (legacy)

- `apps/voice/ws_transport.py` (PR#1)
- `apps/voice/stream_transport.py` (PR#1)
- `apps/voice/svc_stream.py` (PR#3)
- `apps/voice/state.py` (PR#3)
- `apps/voice/ptt_state.py` (PR#3)
- `apps/voice/transport.py` (PR#4)

**Migracja**: patrz `docs/modules/voice.md` → sekcja "Deprecated / Legacy Files"



---

## Odniesienia

- `AGENT.md` — kontrakt i zasady pracy (coding, Done, quality gate).
- `PROJECT.md` — wizja, roadmapa.
- `config/face.toml` — strojenie mimiki.
- `scripts/dev_face-lcd-direct.py` — demo i diagnostyka renderera/LCD.
- `tests/` — testy (m.in. źrenice, blink, look, clamp).

