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
  - Wyniki zapisują do `snapshots/` / `data/` (ostatnia klatka, surowe ujęcia) i publikują eventy (np. `vision.person`).

### 4) Głos / Chat

- **Voice** — socket `` (opcjonalnie TCP `VOICE_TCP_PORT`).
  - Moduły: VAD, KWS, TTS; integracja z API/Chat przez bus.
- **Chat** — integracja przez `/api/chat/*` + wymiana stanów na busie.

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
- `vision.face`, `vision.person`, `vision.motion`
- `voice.state`, `voice.kws`, `voice.vad`
- `face.state`, `face.render`

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
| `tools/`       | Narzędzia                                            |
| `tests/`       | Testy unit/integration                               |

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
- `tools/newface_lcd_direct.py` — tryb demo (LCD/PNG).

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

## Odniesienia

- `AGENT.md` — kontrakt i zasady pracy (coding, Done, quality gate).
- `PROJECT.md` — wizja, roadmapa.
- `config/face.toml` — strojenie mimiki.
- `tools/newface_lcd_direct.py` — demo i diagnostyka renderera/LCD.
- `tests/` — testy (m.in. źrenice, blink, look, clamp).

