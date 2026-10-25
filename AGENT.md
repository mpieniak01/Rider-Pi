# Rider-Pi Apps — **AGENT** (kontrakt dla asystenta kodu)

> **Cel:** prowadź bezpieczne przyrosty, które działają na RPi. Szanuj istniejące interfejsy. Utrzymuj energię/CPU nisko. Zależności i testy rozdziela [polityka środowisk](docs_pl/POLITYKA_SRODOWISK.md).

---

## 1) Zakres i odpowiedzialność

**Możesz modyfikować tylko:**
- `services/**` – warstwa usług (API, bridge, rejestry, web sockety).
- `apps/**` – aplikacje (UI/face, camera, vision, voice, motion).
- `web/**` – zasoby webowe.
- `tests/**` – testy jednostkowe/integracyjne.
- `config/**` – jedynie pliki konfiguracyjne.
- `scripts/dev_pi-deploy.py` – krótki podgląd i wydanie aplikacji przez Git/SSH.
- `docs/**`, `docs_pl/**`, główne przewodniki i reguły dokumentacji.
- `Makefile`, `pytest.ini`, `pyproject.toml`.

**Nie wolno:**
- zmieniać pinów/sprzętu ani unitów `systemd/` poza tymi wymienionymi w `scripts/systemd-sync.sh`,
- instalować doraźnie pakietów na robocie; zmiana runtime urządzenia wymaga osobnego planu,
- instalować globalnie w Ubuntu, w Venom lub środowisku Rider-PC; deklarowane braki WSL Rider-Pi uzupełniaj w istniejącym `.venv` zgodnie z polityką środowisk,
- uruchamiać długowiecznych demonów poza `systemd`,
- wysyłać telemetrii/eksfiltracji.

### 1.1) Wielkość plików Python

- Wydziel spójne warstwy (np. transport, state, chunks, orkiestracja).
- MOVE-ONLY: przenoś całe klasy/funkcje, nie twórz szkieletów.
- Zapewnij re-eksporty, aby publiczne importy działały jak wcześniej.
- Po każdym kroku uruchom ruff i pytest.
- **Wielkość plików Python:** do 600 linii bez uwag; 601–800 linii to ostrzeżenie do oceny spójności; powyżej 800 linii bramka blokuje zmianę. Podział wynika z odpowiedzialności kodu, a nie samego przekroczenia 600 linii.

---

## 2) Środowisko runtime

- **Platforma:** Raspberry Pi (obraz producenta, Debian 11/Bullseye), **Python 3.9**.
- **Pakiety Pi:** wymagane dla aktywnego profilu, bez automatycznej instalacji zestawu test/dev.
- **WSL:** istniejący `.venv` Rider-Pi także dla worktree; zestaw `config/agent/requirements-wsl.txt`, lokalny pip i wspólny cache. `pyzmq` jest wymagany dla BUS. Brak pakietu WSL nie jest ograniczeniem robota.
- **I/O sprzetowe:**
  - UART `/dev/ttyAMA0` – docelowo jeden właściciel ruchu i odczytów.
    Sprawdź posiadacza przed uruchomieniem komponentu; obecne ścieżki opisuje
    [architektura ruchu](docs_pl/apps/motion.md). Nie uruchamiaj drugiego adaptera na zajętym UART.
  - LCD ILI9xx – przez `drivers/lcd/driver_ili9xx.py` (RAW/ShowImage), bez bezpośrednich SPI-write w innych miejscach.
  - **Orientacja LCD:** ekran 2″ jest w tym urządzeniu zamontowany bokiem względem orientacji
    fabrycznej. Zachowaj ten montaż. Dla buźki pozostaw kompensację obrazu `FACE_LCD_ROTATE=270`;
    splash wybiera `SPLASH_ROTATE`, przy jego braku `PREVIEW_ROT`, potem `splash_lcd_rotate`
    z konfiguracji buźki (domyślnie 270). Zmiana obrotu kamery może więc wpływać na splash. Nie zmieniaj
    globalnego obrotu wyświetlacza przy pracy nad pojedynczym widokiem.

---

## 3) Interfejsy, których nie łamiemy (kontrakty)

### HTTP API (8080)
- GET /healthz: zdrowie; GET /api/control/state i /api/safety: brama v1 oraz server_time.
- POST /api/control: aktuatory wymagaja request_id/source/generation/seq/ts/TTL.
- POST /api/safety: ARM/clear wymagaja planu i zgody; STOP/E-Stop zawsze dostepne.
- POST /api/chat/* i serwowanie plikow zachowuja swoje interfejsy.

### BUS (ZMQ 5555/5556)
- Polecenia: motion.command; stan/potwierdzenie: motion.state, motion.ack.
- Legacy tematy aktuatorow wymagaja tej samej koperty. Passive tracking nie uzbraja ruchu.

### Renderer twarzy
- `apps/draw/face_primitives.py: draw_face(canvas, cfg, model, guide=False, quality="fast")` – **nie zmieniaj sygnatury**.
- Pupil: drift+clamp, sprzęgło blink→look – sterowane ENV (patrz §7).

---

## 4) Definicja Done

- Działa na RPi; brak regresji w API i podstawowych ścieżkach.
- Przechodzą kontrole dobrane do zmiany; funkcje sprzętowe potwierdź na Pi.
- Krótka iteracja może mieć tylko powiązany test w WSL i test na urządzeniu;
  pełny `make test` nie jest obowiązkowy przed każdym podglądem.
- Wydanie wymaga review PR i zielonych istniejących kontroli CI;
  wersja sprawdzona na Pi musi odpowiadać wydaniu.
- Zmiana portów/usług → aktualizacja `ARCHITECTURE.md`.
- Zmiany opisane w `docs/` (skrót w commitach).

---

## 5) Workflow developerski

- Jedno Issue = jeden przyrost.
- Gałąź: `codex/<nr>-krotki-opis`.
- Commity: `feat|fix|chore(scope): opis (nr)`.
- PR: opis + *Fixes <nr>* jeśli zamyka Issue.
- Dwie ścieżki: lokalny commit → `make pi-preview` → test na Pi; następnie
  push → PR/review → merge → `make pi-release PI_COMMIT=<hash>`.
- Powrót z podglądu: `make pi-rollback`. Procedura: [wdrożenie](docs_pl/WDROZENIE.md).

**Przykład:**
```bash
# start
git switch -c codex/42-pupil-drift-tuning

# praca
# ewentualna krótka kontrola lub powiązany test w WSL

# commit
git commit -m "feat(face): pupil drift clamp improves edge cases (42)"

# podgląd i test funkcji na fizycznym Pi przed publikacją
make pi-preview

# PR/push
git push -u origin codex/42-pupil-drift-tuning
```

---

## 6) Testowanie


### Kategorie testów — obowiązująca zasada

- **Automatyczne:** testy programowe z mockiem/symulatorem, odizolowane od
  rzeczywistego robota i jego magistrali poleceń, uruchamiane w WSL/CI. Nie mogą uzbrajać urządzenia. Pełnego pytest/coverage nie przenosimy na Pi.
- **Sprzętowe bez ruchu:** np. odczyt kamery, LCD lub telemetrii; osobny zakres
  sprawdzenia, z potwierdzeniem że nie uruchamia autonomii ani napędów.
- **Ruch/aktuatory:** jazda, obrót, wysokość, balans, akcje i scenariusz mogący
  poruszyć robotem — wyłącznie ręczny test po wyraźnej zgodzie operatora na
  konkretny plan. Nigdy nie wywołuj go automatycznie przez pytest/E2E/CI,
  skrypt ogólnej diagnostyki, wdrożenie, harmonogram lub wejście na stronę panelu.
  Zgoda na kamerę, uruchomienie usług albo wdrożenie nie jest zgodą na ruch.

Zgoda na jedną próbę nie uzbraja następnych testów. Przed próbą operator
potwierdza przestrzeń, podłoże, kabel i sposób zatrzymania. Diagnostyka nie
kasuje E-Stop ani nie włącza ruchu dla ułatwienia testu.
- **Szybkie single-tests** (przykłady dla twarzy):
```bash
pytest -q tests/test_renderer_basics.py::test_basic_frame_renders_and_pupils_visible
pytest -q tests/test_pupil_drift.py::test_pupil_drift_changes_bbox
pytest -q tests/test_blink_shift_coupling.py::test_blink_can_trigger_look_when_coupling_enabled
```
- **REST, odczyt bez ruchu**:
```bash
curl -s http://localhost:8080/healthz | jq .
```
- Test ruchu wymaga przygotowanego robota i zgody operatora (sekcja 9).
- **BUS spy:** `python3 scripts/dev_bus-sub.py motion`
- **Demo LCD/PNG (face):**
```bash
sudo -E env -u FACE_MOUTH_SHAPE -u FACE_MOUTH_OPEN \
  FACE_IDLE_ENABLE=1 FACE_IDLE_BLINK_SEC=3.4 FACE_IDLE_LOOK_P=0.22 FACE_IDLE_LOOK_SEC=3.4 \
  FACE_GESTURE_LOOK_AMP=0.32 \
  FACE_EYES_FOLLOW_KX=0.12 FACE_EYES_FOLLOW_KY=0.22 \
  FACE_BROW_FOLLOW_KX=0.03 FACE_BROW_FOLLOW_KY=0.06 \
  FACE_PUPIL_DRIFT_AMP_K=0.02 FACE_PUPIL_DRIFT_FREQ=0.8 \
  python3 scripts/dev_face-lcd-direct.py --expr neutral --fps 20 --rotate 270 --secs 8 --stats
```

---

## 7) Konfiguracja mimiki (gałki ENV / config)

**ENV (runtime):**
- `FACE_IDLE_ENABLE` (0/1), `FACE_IDLE_BLINK_SEC`, `FACE_IDLE_LOOK_P`, `FACE_IDLE_LOOK_SEC`.
- `FACE_GESTURE_BLINK_DUR`, `FACE_GESTURE_BLINK_HOLD`.
- `FACE_GESTURE_LOOK_T`, `FACE_GESTURE_LOOK_AMP`.
- **Pupil:** `FACE_PUPIL_DRIFT_AMP_K`, `FACE_PUPIL_DRIFT_FREQ`, `FACE_PUPIL_CLAMP_RATIO`.
- **Sprzęgło:** `FACE_BLINK_SHIFT_PROB`.
- **Follow:** `FACE_EYES_FOLLOW_KX/KY`, `FACE_BROW_FOLLOW_KX/KY` (małe wartości!).
- **Debug:** `FACE_DEBUG_MOUTH`.

**`config/face.toml` (dla renderera – klucze lowercase):**
- `head_ky`, `brow_y_k`, `mouth_y_k`.
- Wstążka ust: `mouth_ribbon_taper_k`, `mouth_small_th_k_base`.
- Per-shape: `mouth_*_lift_k`, `mouth_*_arch_k`.
- Zachowane aliasy `FACE_*` dla zgodności (loader może mapować).

> Zasada: **modyfikuj preferencyjnie ENV** dla strojenia; TOML trzymaj spójny z domyślną stylistyką.

---

## 8) Lint/format

- **Ruff jest bramką jakości**: hook `pre-commit` uruchamia `ruff check/format` przy każdym commicie **i** na CI.
- **Wersja narzędzia**: Projekt wymusza użycie **ruff==0.6.9**. Upewnij się, że masz zainstalowaną dokładnie tę wersję, aby uniknąć różnic w formatowaniu względem CI.
- Commity z błędami lintu **są odrzucane**.
- **Nie omijaj** hooków `--no-verify` (dopuszczalne tylko lokalnie przy WIP – nigdy na `main`).
- **Miejsce konfiguracji**: `pyproject.toml` (nie zmieniaj zasad bez uzasadnienia w PR).
- **Wyjątki/wyciszenia**: preferuj lokalne `# noqa: ...` lub wpis w `per-file-ignores` **tylko** dla testów; unikaj globalnych ignorów.
- **Reguły niezmieniane automatycznie**: `unfixable = ["UP006","UP045"]` – nie próbuj masowych modernizacji typów, jeśli psuje to zgodność.

**Szybkie komendy:**
```bash
ruff check apps/ tests/ services/ common/ --statistics
ruff format
```

---

### Sonar po publikacji i scaleniu

- Workflow `.github/workflows/sonar.yml` jest właścicielem skanów main i PR z tego repozytorium.
- Po merge czekaj na wynik workflow main dla dokładnego SHA; nie uruchamiaj równolegle lokalnego skanera.
- Ręczne odświeżenie main wykonuj przez `workflow_dispatch` tego workflow na main; zachowuje wspólną grupę współbieżności.
- Kanoniczny launcher lokalny odmawia wysyłania analiz przy aktywnym workflow. Tryb `--check` służy tylko do odczytu.
- Procedura i rozróżnienie raportu Sonara od statusu CI: [bramka jakości](docs_pl/BRAMKA_JAKOSCI.md).

---

## 9) Bezpieczeństwo i walidacja

- Waliduj aktualny kontrakt `/api/control` i ponownie polecenie u wykonawcy.
- `SAFE_MAX_DURATION` i `MIN_CMD_GAP` – egzekwuj limity czasu i częstotliwości.
- W razie wątpliwości – **nie wykonuj**; zwróć błąd i log z sugestią parametru.

### Robot fizyczny podczas developmentu

- Robot może być na kablu zasilania. Do potwierdzenia przygotowania przez operatora
  traktuj go jako niegotowy do ruchu. Najpierw opisz planowany ruch/czas/prędkość,
  następnie uzyskaj potwierdzenie miejsca, podłoża i bezpiecznego kabla.
- Jazda, skręt, wysokość i balans to działania fizyczne. Dla zmian panelu/API
  używaj odczytów oraz mocków w istniejącym lokalnym środowisku WSL.
- Nie uzbrajaj ruchu ani nie kasuj E-Stop podczas diagnozy. Nie uruchamiaj
  testu/demo bez odczytania jego skutków; niektóre skrypty zmieniają flagi.
- `MOTION_ENABLE=0`, `DRY_RUN`, etykieta S0/S11 oraz `make stop-all` nie są
  potwierdzeniem globalnej blokady. Podgląd wdrożenia nie rozbraja wykonawców.
- Uwzględniaj rozpędzanie, bezwładność i drogę hamowania. Zwykły STOP z rampą
  i zatrzaśnięty awaryjny STOP mają różne zadania. Nie odtwarzaj zaległych
  poleceń po ponownym uzbrojeniu. Obecne luki opisuje [bezpieczeństwo](docs_pl/apps/safety.md).

---

## 10) Energooszczędność / wydajność

- Vision/Kamera – **OFF domyślnie**; włączaj tylko przy potrzebie.
- Głos, tracking i nawigację uruchamiaj na żądanie dla konkretnego scenariusza;
  po teście sprawdź faktyczne procesy, bo zatrzymanie targetu nie musi zatrzymać
  usług współdzielonych. Odczyt baterii nie jest automatyczną blokadą ruchu.
- LCD push – używaj fast-path RAW RGB565 tam, gdzie dostępne.
- Unikaj pętli aktywnych; preferuj timery i taktowanie stałe.

---

## 11) Logowanie

- Zwięzłe, z prefiksami: `[api]`, `[bridge]`, `[vision]`, `[voice]`, `[face]`.
- Bez danych wrażliwych; poziom INFO/DEBUG kontrolowany ENV.

---

## 12) Współbieżność

- Jeden aktywny przyrost naraz.
- Jeżeli istnieje `.codex.lock` – nie wprowadzaj zmian.

---

## 13) Noty migracyjne — Face LCD fast-path (2025‑09)

- Usunięto zależności od `_apps/ui/face_renderers.py`.
- Driver LCD: `drivers/lcd/driver_ili9xx.py` (mock w CI + SPI w runtime).
- Fast-path RAW RGB565; mock zapisuje PNG/565/meta.
- Konfiguracja panelu/rotacji: `apps/ui/face/panel_cfg.py`; I/O: `apps/ui/face/face_io.py`.
- CLI: `scripts/dev_face-lcd-direct.py` i `scripts/dev_face-cli.py`.
- Testy: `tests/test_face_raw_fastpath.py`, `tests/test_no_underscore_apps_dependency.py`.

**Przykład (mock, fast-path):**
```bash
export FACE_LCD_BACKEND=mock
export FACE_LCD_ROTATE=270
export FACE_LCD_SPI_HZ=32000000
python3 scripts/dev_face-lcd-direct.py --expr neutral --secs 4 --stats
```

---

## 14) Checklist PR (skrót)

- [ ] Zmiany tylko w dozwolonych katalogach.
- [ ] Bez nowych zależności.
- [ ] `pytest` zielony (lokalnie, kluczowe testy twarzy).
- [ ] Lint/format (ruff) wykonany.
- [ ] `ARCHITECTURE.md` zaktualizowany przy zmianie usług/portów.
- [ ] Logi z prefiksami.
- [ ] Komentarz w commitach i link do Issue.

## Dokumentacja i rozruch

Stosuj [politykę dokumentacji](docs_pl/POLITYKA_DOKUMENTACJI.md). Plany i raporty są lokalne.
Przy pracach aplikacyjnych zachowuj rozruch, sieć i SSH; zobacz [wdrożenie](docs_pl/WDROZENIE.md).
