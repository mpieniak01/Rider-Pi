# Rider-Pi Apps — AGENT
## Misja

- Minimalne zużycie energii i stabilność usług.
- Wydajny prosty kod, małe moduły, łatwy rollback.

## Zasady kodowania

- **Limit wielkości**: maks. 600 linii na plik.
- **Styl**: małe, czytelne zmiany, bez nadmiarowych abstrakcji.
- **Zakres**: edytuj tylko `services/*`, `apps/ui/*`, `web/*`, `tests/*`, `Makefile`.
- **Zakazy**: nie zmieniaj hardware pinów ani unitów systemd poza listą w `ops/systemd_sync.sh`.
- **Procesy**: bez długotrwałych demonów, bez telemetrii.

## Architektura (kontekst)

- **API**: `rider-api.service` (port 8080) — jedyny punkt wejścia HTTP.
- **Web-Motion Bridge**: `rider-web-bridge.service` (port 8081) — uproszczone ruchy.
- **Broker ZMQ**: porty 5555/5556 — PUB/SUB.
- **Motion Bridge**: jedyny dostęp do UART `/dev/ttyAMA0`.
- **Vision/Camera**: generują pliki (`snapshots/`, `data/`) serwowane przez API.
- **Voice**: socket `/run/rider-voice.sock` (opcjonalnie TCP `VOICE_TCP_PORT`).
- **Chat**: brak własnego portu, integracja przez `/api/chat/*` i bus.
- **Face**: `apps/ui/face.py` — render emocji, serwowany przez API.

## Środowisko uruchomieniowe

- Agent działa w środowisku Raspberry Pi (Debian/Bookworm, Python 3.11).
- Dozwolone jest korzystanie tylko z pakietów już obecnych w `requirements.txt` oraz tych instalowanych przez `make setup`.
- **Nie instaluj nowych zależności z Internetu** (pip install online). Jeśli potrzebna biblioteka nie jest w repo, zgłoś to jako brak zamiast instalować.
- Dodatkowe moduły systemowe (np. libcamera, zmq) są już zainstalowane w obrazie i dostępne.
- Testy i uruchamianie odbywają się wyłącznie w tym środowisku.

## Definicja Done

- Kod działa w środowisku Raspberry Pi.
- `make test` przechodzi (pytest, testy integracyjne).
- Nowa funkcjonalność ma prosty test (unit/integration).
- Jeśli zmieniono porty/usługi → zaktualizowany `ARCHITECTURE.md`.
- Zmiany udokumentowane w `docs/`.

## Testowanie po stronie Codex

- **Jednostkowe/integracyjne:** `make test` (pytest).
- **E2E REST:**
  ```bash
  curl -s http://localhost:8080/healthz | jq .
  curl -s -X POST http://localhost:8080/api/control -H 'Content-Type: application/json' \
    -d '{"action":"move","vx":0.4,"yaw":0,"duration":0.2}'
  curl -s -X POST http://localhost:8080/api/control -H 'Content-Type: application/json' \
    -d '{"action":"stop"}'
  ```
- **Bus spy:** `python3 tools/sub.py motion`
- **Render buźki:** wywołaj `apps/ui/face.py` i zapisz do `artifacts/`.

## Dokumentowanie zmian

- Każdy przyrost dokumentuj:
  - wpisem w `docs/N_changes_codex_YYYY-MM-DD.md` (gdzie `N` to numer Issue, a `YYYY-MM-DD` to data),
  - krótkim opisem commitów (`feat:`, `fix:`, `chore:`),
  - jeśli zmieniasz API/usługi — aktualizuj `ARCHITECTURE.md`.

## Bezpieczeństwo i walidacja

- Waliduj komendy: tylko `move`, `stop`, `turn`.
- Limit czasu ruchu ≤ `SAFE_MAX_DURATION`.
- Przerwa między komendami ≥ `MIN_CMD_GAP`.
- W niepewności: pytaj zamiast wykonywać.

## Zakres i granice

- Dozwolone są zmiany w katalogach: `services/`, `apps/`, `web/`, `tests/`, `docs/` — zgodnie z istniejącą strukturą repozytorium i przy zachowaniu konwencji.
- **Zakazane zmiany:** pinów/sprzętu, plików w `systemd/` poza `ALLOW_UNITS`, portów bez aktualizacji w `ARCHITECTURE.md`.
- **Energia:** kamera i vision zawsze domyślnie OFF.

## Quality gate

- **Limit:** ≤ 600 linii na plik.
- **Styl:** Python 3.11, czytelne funkcje, brak magii.
- **Logi:** krótkie, z prefiksem `[api]`, `[bridge]`, `[chat]`.
- **Kontrakty:** nie łam `/api/control`, `/api/chat/*`, `draw_face()`.

## Współbieżność

- Tylko jeden aktywny przyrost na raz.
- Jeśli w repo jest `.codex.lock` — nie wprowadzaj zmian.

## Identyfikacja przyrostów

- **Źródło numeru**: używamy numerów **GitHub Issues** (N). Każdy atomowy przyrost = jedno Issue.
- **Konwencja commitów**: dopisuj numer na końcu wiadomości, np. `feat(api): control router OK (12)`.
- **Gałąź robocza**: `codex/12-krótki-opis`.
- **SPRINT.md**: nagłówek zaczyna się od `Issue 12 – …`.
- **Relacje**: jeśli PR rozwiązuje zadanie, użyj `Fixes 12` w opisie PR.
- **Tagi**: pozostajemy przy schemacie wersji (`v0.x.y`, np. jak w repo), opcjonalnie w release notes wspominamy numer Issue.

> Uwaga: w obecnych commitach i tagach nie ma stałej konwencji numerów; repo używa tagów wersji typu `v0.9.1-chat`, `v0.6` (patrz zakładka *Tags*). Od teraz N = numer Issue na GitHubie, co zapewnia spójne linkowanie i historię.

## Odniesienia

1. **AGENT.md** (ten plik) – kontrakt Codex.
2. **ARCHITECTURE.md** – porty, usługi, bus.
3. **PROJECT.md** - wizja proejktu

---

## Migration notes: Face LCD fast-path (2025-09)

- Usunięto wszelkie zależności od `_apps/ui/face_renderers.py` w buźce, API i narzędziach.
- Nowy driver LCD (`apps/ui/face/driver/`): mock (domyślny, CI) oraz szkielet SPI.
- Fast-path RAW RGB565: szybkie wypychanie klatki do bufora, mock zapisuje PNG, RGB565, meta.
- Konfiguracja panelu i rotacji: `apps/ui/face/panel_cfg.py` (ENV/CLI), konwersje: `apps/ui/face/face_io.py`.
- Nowe CLI: `tools/face_cli.py` (opcja --force, --expr, --rotate, --fit, --stats, backend mock domyślny).
- Testy: `tests/test_face_raw_fastpath.py` (mock, fast-path, meta), `tests/test_no_underscore_apps_dependency.py` (brak _apps).
- Brak zmian w systemd/autostart, brak regresji w API.

### Przykładowe uruchomienie (mock, fast-path):

```bash
export RIDER_APPS_PATH="_apps:apps"
export FACE_LCD_BACKEND=mock
export FACE_LCD_ROTATE=270
export FACE_LCD_SPI_HZ=32000000
export FACE_LCD_FIT=fill
python3 tools/face_cli.py --expr happy --rotate 270 --force raw:rgb565 --stats
ls -lah /tmp/face_last.*
cat /tmp/face_last.meta.json
```