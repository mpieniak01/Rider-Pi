# Rider-Pi — język poleceń
# użycie: make <komenda>  (alias: robot <komenda> jeśli masz alias)
PY      ?= /usr/bin/python3
SUDO    ?= sudo
ROOT    ?= $(CURDIR)

# Domyślne LCD ENV (możesz nadpisać przy wywołaniu: FACE_LCD_ROTATE=270 make lcd-on)
FACE_LCD_ROTATE ?= 270
FACE_LCD_SPI_HZ ?= 32000000

# Aktualny zestaw usług (repo-first systemd)
SYSTEMD_SERVICES = rider-broker.service rider-api.service rider-vision.service rider-cam-preview.service

# VOICE (serwer www + CLI; opcjonalne VOICE_ARGS, np. ' --lang pl --tts backend=openai ')
VOICE_BIND ?= 127.0.0.1:8092

# Dziedziczenie klucza z ~/.bash_profile do komend voice-*
ENV_FROM_BASH = OPENAI_API_KEY="$$(bash -lc 'source ~/.bash_profile >/dev/null 2>&1; printf %s "$$OPENAI_API_KEY"')"

# ───────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "Rider-Pi — język projektu"
	@echo "  make broker           # uruchom brokera (foreground)"
	@echo "  make api              # uruchom API (foreground)"
	@echo "  make up               # restart broker+api (systemd)"
	@echo "  make status           # status broker+api+vision"
	@echo "  make status-all       # status wszystkich usług rider-*"
	@echo "  make logs-broker      # logi brokera"
	@echo "  make logs-api         # logi API"
	@echo "  make logs-preview     # logi cam-preview"
	@echo "  make logs-all         # logi wszystkich kluczowych"
	@echo ""
	@echo "  make stop-all         # zatrzymaj wszystkie usługi Rider-Pi"
	@echo "  make safemode         # tryb awaryjny (kill vendor, stop, LCD off, LED off)"
	@echo ""
	@echo "  make preview-run      # podgląd kamery (interactive, bez systemd)"
	@echo "  make preview-on       # start cam-preview (systemd)"
	@echo "  make preview-off      # stop  cam-preview (systemd)"
	@echo "  make preview-status   # status cam-preview"
	@echo ""
	@echo "  make bus-spy          # podsłuch magistrali"
	@echo ""
	@echo "  make vision-on        # start vision (dispatcher)"
	@echo "  make vision-off       # stop vision"
	@echo "  make vision-burst     # vision na czas (SECONDS=120 domyślnie)"
	@echo "  make vision-status    # status vision"
	@echo ""
	@echo "  make lcd-on           # włącz LCD (wake + DISP_ON)"
	@echo "  make lcd-off          # wyłącz LCD (black + SLEEP, + próba BL)"
	@echo "  make lcd-reset        # panel reset (RST) + ON"
	@echo "  make lcd-black        # wyczyść ekran do czerni (presenter)"
	@echo "  make lcd-on-hard      # twarde ON (piny + SPI), z fallbackiem BL"
	@echo "  make lcd-off-hard     # twarde OFF (piny + SPI), z wymuszeniem BL"
	@echo ""
	@echo "  make face-direct      # bezpośredni renderer LCD (scripts/dev_face-lcd-direct.py)"
	@echo "  make face-api-png     # render PNG przez face_api → /tmp/face_api.png"
	@echo "  make face-api-lcd     # jednorazowy push na LCD przez face_api"
	@echo "  make face-testcard    # plansza testowa na LCD"
	@echo "  make face-bench       # krótki benchmark FPS"
	@echo ""
	@echo "  make voice-run        # nasłuch ciągły (listen)"
	@echo "  make voice-ptt        # push-to-talk (ptt)"
	@echo "  make voice-once       # pojedyncza interakcja (once)"
	@echo "  make voice-once-realtime  # pojedyncza interakcja (realtime WebSocket)"
	@echo "  make voice-listen-realtime # nasłuch ciągły (realtime WebSocket)"
	@echo "  make voice-asr-file FILE=path.wav   # rozpoznaj mowę z pliku"
	@echo "  make voice-tts TEXT='Hello'         # synteza + odtworzenie"
	@echo "  make voice-web        # uruchom serwer web UI (bind: $(VOICE_BIND))"
	@echo ""
	@echo "  NEW VOICE (CLI-first with ALSA pre-flight):"
	@echo "  make voice-once-new   # pojedyncza interakcja (nowy CLI)"
	@echo "  make voice-ptt-new    # push-to-talk (nowy CLI)"
	@echo "  make voice-listen-new # nasłuch ciągły (nowy CLI)"
	@echo "  make voice-diag       # diagnostyka systemu"
	@echo "  make voice-free       # zwolnij urządzenia ALSA"
	@echo "  make voice-smoke      # testy podstawowe (bez audio/sieci)"
	@echo ""
	@echo "  make test             # testy"
	@echo "  make bench            # benchmark detekcji"
	@echo "  make clean            # sprzątanie cache"
	@echo "  make tree             # drzewo repo"
	@echo "  make health           # /healthz API (port 8080)"
	@echo ""
	@echo "  [DEPRECATED] ssd-on/off/status/logs, preview-ssd  -> patrz: preview-*"

# ───────────────────────────────────────────────
# DEV RUN (foreground)
.PHONY: broker api
broker:
	-@fuser -k 5555/tcp 5556/tcp 2>/dev/null || true
	$(PY) services/broker.py

api:
	$(PY) -u -m services.api_server

# ───────────────────────────────────────────────
# SYSTEMD
.PHONY: up stop-all status status-all logs-broker logs-api logs-all logs-preview
up:
	@$(SUDO) systemctl restart rider-broker.service rider-api.service

stop-all:
	-@$(SUDO) systemctl stop $(SYSTEMD_SERVICES) || true

status:
	@systemctl --no-pager --full status rider-broker.service | sed -n '1,20p'
	@systemctl --no-pager --full status rider-api.service    | sed -n '1,20p'
	@systemctl --no-pager --full status rider-vision.service | sed -n '1,20p'

status-all:
	@systemctl list-units --type=service --all | grep -E 'rider-(broker|api|vision|cam-preview)'

logs-broker:
	@journalctl -u rider-broker.service -n 120 --no-pager

logs-api:
	@journalctl -u rider-api.service -n 120 --no-pager

logs-preview:
	@journalctl -u rider-cam-preview.service -n 120 --no-pager || true

logs-all:
	@journalctl -u rider-broker.service -n 80 --no-pager
	@echo "───"
	@journalctl -u rider-api.service -n 80 --no-pager
	@echo "───"
	@journalctl -u rider-vision.service -n 80 --no-pager
	@echo "───"
	@journalctl -u rider-cam-preview.service -n 80 --no-pager || true

# ───────────────────────────────────────────────
# SAFE MODE
.PHONY: safemode face-kill lcd-off-safe
safemode:
	-@$(ROOT)/scripts/sys_camera-kill.sh || true
	-@$(MAKE) face-kill
	-@$(SUDO) systemctl stop $(SYSTEMD_SERVICES) || true
	-@$(MAKE) lcd-off
	-@$(PY) $(ROOT)/scripts/sys_led-control.py off || true

# zabij wszystko co może rysować na LCD
face-kill:
	-@pkill -f 'newface|lcd_presenter|api_server|face_api|preview_lcd|xgoscreen' || true

# tryb „na pewniaka”: vendor kill + stop-all + off
lcd-off-safe:
	@$(MAKE) vendor-kill
	@$(MAKE) stop-all
	@$(MAKE) lcd-off

# ───────────────────────────────────────────────
# OPS HELPERS
.PHONY: lcd-on lcd-off lcd-reset lcd-black vendor-kill vendir-kill
lcd-on:
	@echo "== Włączam LCD (wyjście ze snu) =="
	@FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) $(SUDO) $(PY) $(ROOT)/scripts/sys_lcd-control.py on || true

# U CIEBIE: brak sterowalnego BL → najlepszy efekt to 'black' + 'sleep'.
# Próba wymuszenia BL przez GPIO zostaje (nie przeszkadza).
lcd-off:
	@echo "== Wyłączam LCD (black + sleep) =="
	@$(PY) $(ROOT)/scripts/dev_lcd-clear.py
	@FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) $(SUDO) $(PY) $(ROOT)/scripts/sys_lcd-control.py off || true
	@BL=$${FACE_LCD_BL_PIN:-13}; AH=$${FACE_LCD_BL_ACTIVE_HIGH:-1}; \
	if [ "$$AH" = "1" ]; then sudo raspi-gpio set $$BL op dl; else sudo raspi-gpio set $$BL op dh; fi; \
	echo "BL pin=$$BL (wygaszony)"; raspi-gpio get $$BL

lcd-reset:
	@echo "== RESET panelu LCD =="
	@FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) $(SUDO) $(PY) $(ROOT)/scripts/sys_lcd-control.py reset || true

lcd-black:
	@$(PY) $(ROOT)/scripts/dev_lcd-clear.py

vendor-kill:
	@echo "== Ubijam procesy dostawcy kamery/LCD =="
	@$(SUDO) systemctl stop yahboom* || true
	@$(SUDO) systemctl stop rider-vendor* || true
	@$(SUDO) systemctl stop jupyter.service || true
	@$(SUDO) systemctl start jupyter.service || true

# alias dla literówki
vendir-kill:
	@$(MAKE) vendor-kill

# ───────────────────────────────────────────────
# TOOLS / DIAG
.PHONY: preview-run bus-spy
preview-run:
	@echo "Podgląd (Ctrl+C aby zakończyć)..."
	$(PY) -u apps/camera/preview_lcd.py

bus-spy:
	$(PY) scripts/diag_bus-spy.py

# ───────────────────────────────────────────────
# CAM PREVIEW (systemd on-demand) + aliasy wsteczne
.PHONY: preview-on preview-off preview-status
preview-on:
	@$(SUDO) systemctl start rider-cam-preview.service

preview-off:
	@$(SUDO) systemctl stop rider-cam-preview.service || true

preview-status:
	@systemctl --no-pager --full status rider-cam-preview.service | sed -n '1,25p' || true

# aliasy DEPRECATED (zachowana kompatybilność)
.PHONY: ssd-on ssd-off ssd-status logs-ssd preview-ssd
ssd-on:
	@echo "[DEPRECATED] użyj: make preview-on"
	@$(MAKE) preview-on
ssd-off:
	@echo "[DEPRECATED] użyj: make preview-off"
	@$(MAKE) preview-off
ssd-status:
	@echo "[DEPRECATED] użyj: make preview-status"
	@$(MAKE) preview-status
logs-ssd:
	@echo "[DEPRECATED] użyj: make logs-preview"
	@$(MAKE) logs-preview
preview-ssd:
	@echo "[DEPRECATED] użyj: make preview-run"
	@$(MAKE) preview-run

# ───────────────────────────────────────────────
# VISION CONTROL
.PHONY: vision-on vision-off vision-burst vision-status
vision-on:
	@echo "== Vision ON =="
	@$(ROOT)/scripts/sys_vision-control.sh on

vision-off:
	@echo "== Vision OFF =="
	@$(ROOT)/scripts/sys_vision-control.sh off

vision-burst:
	@echo "== Vision BURST ($(or $(SECONDS),120)s) =="
	@$(ROOT)/scripts/sys_vision-control.sh burst $(or $(SECONDS),120)

vision-status:
	@$(ROOT)/scripts/sys_vision-control.sh status

# ───────────────────────────────────────────────
# LED CONTROL
.PHONY: led-on led-off led-blink led-status led-auto
led-on:
	@echo "== LED ON =="
	@$(PY) $(ROOT)/scripts/sys_led-control.py on

led-off:
	@echo "== LED OFF =="
	@$(PY) $(ROOT)/scripts/sys_led-control.py off

# Użycie: make led-blink HZ=2  (albo ON=200 OFF=200)
led-blink:
	@echo "== LED BLINK =="
	@if [ -n "$(HZ)" ]; then \
		$(PY) $(ROOT)/scripts/sys_led-control.py blink --hz $(HZ); \
	else \
		$(PY) $(ROOT)/scripts/sys_led-control.py blink --on-ms $${ON:-200} --off-ms $${OFF:-200}; \
	fi

led-status:
	@$(PY) $(ROOT)/scripts/sys_led-control.py status

led-auto:
	@echo "== LED AUTO =="
	@$(PY) $(ROOT)/scripts/sys_led-control.py auto

# ───────────────────────────────────────────────
# FACE (helpers)
.PHONY: face-direct face-api-png face-api-lcd face-testcard face-bench
# make face-direct EXPR=happy FPS=20 SECS=5 FORCE=rgb565_3
face-direct:
	@echo "== Face direct (scripts/dev_face-lcd-direct.py) =="
	@FACE_LCD_ROTATE=$(FACE_LCD_ROTATE) FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) \
	$(SUDO) -E $(PY) $(ROOT)/scripts/dev_face-lcd-direct.py \
		--expr $${EXPR:-neutral} --rotate $(FACE_LCD_ROTATE) --spi-hz $(FACE_LCD_SPI_HZ) \
		--fps $${FPS:-20} $${FORCE:+--force $${FORCE}} $${SECS:+--secs $${SECS}} --stats

face-api-png:
	@echo "== Face API → PNG (/tmp/face_api.png) =="
	@ROT=$(FACE_LCD_ROTATE) $(PY) -c 'import os; from services.api_core import face_api; print(face_api.render(backend="png", expr=os.getenv("EXPR","happy"), size=int(os.getenv("SIZE","240")), rotate=int(os.environ.get("ROT","270")), out="/tmp/face_api.png"))'

face-api-lcd:
	@echo "== Face API → LCD (jedna klatka) =="
	@ROT=$(FACE_LCD_ROTATE) HZ=$(FACE_LCD_SPI_HZ) $(PY) -c 'import os; from services.api_core import face_api; print(face_api.render(backend="lcd", expr=os.getenv("EXPR","happy"), size=int(os.getenv("SIZE","240")), rotate=int(os.environ.get("ROT","270")), spi_hz=int(os.environ.get("HZ","32000000"))))'

face-testcard:
	@echo "== LCD testcard (kolorowe pasy) =="
	@FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) $(SUDO) -E $(PY) $(ROOT)/scripts/dev_lcd-testcard.py --rotate $(FACE_LCD_ROTATE) --spi-hz $(FACE_LCD_SPI_HZ)

face-bench:
	@echo "== FACE BENCH =="
	@for HZ in $${HZ_LIST:-32000000 48000000 64000000}; do \
		echo "--- HZ=$$HZ ROT=$(FACE_LCD_ROTATE) (secs=$${SECS:-4}) ---"; \
		FACE_LCD_ROTATE=$(FACE_LCD_ROTATE) FACE_LCD_SPI_HZ=$$HZ \
		$(SUDO) -E $(PY) $(ROOT)/scripts/dev_face-lcd-direct.py \
		  --expr happy --rotate $(FACE_LCD_ROTATE) --spi-hz $$HZ \
		  --secs $${SECS:-4} --stats --force push_frame:rgb565_3 \
		  | sed -n '/^\[stats\]/p;/^\[LCD] Statystyki/p'; \
	done
	@echo "Tip: możesz nadpisać:  HZ_LIST=\"32000000 48000000\"  oraz SECS=6"


# Commented out - face_presets.sh script doesn't exist
# face-neutral:
# 	@bash tools/face_presets.sh neutral --secs 8 --stats

# face-happy:
# 	@bash tools/face_presets.sh happy --secs 8 --stats

# face-sad:
# 	@bash tools/face_presets.sh sad --secs 8 --stats

# ───────────────────────────────────────────────
# GFX / VNC
.PHONY: x-on x-off vnc-virtual-on vnc-virtual-off gfx-status
x-on:
	@echo "== Włączam tryb graficzny + RealVNC (X11, :5900) =="
	@$(SUDO) systemctl set-default graphical.target
	@$(SUDO) systemctl enable --now lightdm
	@$(SUDO) systemctl enable --now vncserver-x11-serviced

x-off:
	@echo "== Wyłączam tryb graficzny, wracam do multi-user (tekst) =="
	@$(SUDO) systemctl disable --now vncserver-x11-serviced || true
	@$(SUDO) systemctl disable --now lightdm || true
	@$(SUDO) systemctl set-default multi-user.target

vnc-virtual-on:
	@echo "== Włączam wirtualny RealVNC (:5901) bez X11 =="
	@$(SUDO) systemctl enable --now vncserver-virtuald

vnc-virtual-off:
	@echo "== Wyłączam wirtualny RealVNC (:5901) =="
	@$(SUDO) systemctl disable --now vncserver-virtuald || true

gfx-status:
	@systemctl status lightdm --no-pager || true
	@systemctl status vncserver-x11-serviced --no-pager || true
	@systemctl status vncserver-virtuald --no-pager || true
	@systemctl get-default

# ───────────────────────────────────────────────
# VOICE (CLI + web)
.PHONY: voice-run voice-ptt voice-once voice-asr-file voice-tts voice-web voice-once-realtime voice-listen-realtime
voice-run:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli listen $(VOICE_ARGS)

voice-ptt:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli ptt $(VOICE_ARGS)

voice-once:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli once $(VOICE_ARGS)

voice-asr-file:
	@if [ -z "$(FILE)" ]; then echo "Usage: make voice-asr-file FILE=path.wav"; exit 1; fi
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli asr --file "$(FILE)" $(VOICE_ARGS)

voice-tts:
	@if [ -z "$(TEXT)" ]; then echo "Usage: make voice-tts TEXT='Hello'"; exit 1; fi
	PYTHONPATH=$(ROOT) $(PY) -m apps.voice.cli tts --text "$(TEXT)" --play $(VOICE_ARGS)

voice-web:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.web --bind $(VOICE_BIND) $(VOICE_ARGS)

# Realtime voice modes with pasuspender for WM8960 duplex support
voice-once-realtime:
	pasuspender -- \
	$(PY) -m apps.voice.cli --config ./config/voice.toml once \
	  --asr transport=realtime language=pl \
	  --chat transport=realtime \
	  --tts transport=realtime voice=ash

voice-listen-realtime:
	pasuspender -- \
	$(PY) -m apps.voice.cli --config ./config/voice.toml listen \
	  --asr transport=realtime language=pl \
	  --chat transport=realtime \
	  --tts transport=realtime voice=ash

# ───────────────────────────────────────────────
# NEW VOICE TARGETS (CLI-first with ALSA pre-flight)
.PHONY: voice-once-new voice-ptt-new voice-listen-new voice-diag voice-free voice-smoke
voice-once-new:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli once --mode stream $(VOICE_ARGS)

voice-ptt-new:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli ptt --mode stream $(VOICE_ARGS)

voice-listen-new:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli listen --mode stream $(VOICE_ARGS)

voice-diag:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli diag --audio $(VOICE_ARGS)

voice-free:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli free $(VOICE_ARGS)

voice-smoke:
	@echo "Voice smoke tests (mock mode, no audio/network)..."
	@echo "Testing config loading..."
	@$(ENV_FROM_BASH) $(PY) -m apps.voice.cli diag --no-network --log-level ERROR
	@echo "Testing WAV utilities..."
	@$(PY) -m pytest tests/test_voice_audio_utils.py::TestWavUtil -v -x
	@echo "Testing PTT state machine..."  
	@$(PY) -m pytest tests/test_voice_ptt_state.py -v -x
	@echo "✓ Smoke tests passed"

# ───────────────────────────────────────────────
# VOICE STREAMING TARGETS (new)
.PHONY: voice-kill voice-stream-once voice-stream-listen
voice-kill:
	@echo "== Killing voice/audio processes =="
	-@pkill -f "apps.voice.cli" 2>/dev/null || true
	-@pkill -f "arecord" 2>/dev/null || true
	-@pkill -f "aplay" 2>/dev/null || true

voice-stream-once: voice-kill
	@echo "== Single streaming interaction =="
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli once \
	  --mode stream \
	  --log-level INFO \
	  --capture device=wm8960_in sample_rate=16000 channels=2 \
	  --playback device=wm8960_out

voice-stream-listen: voice-kill
	@echo "== Continuous streaming (PTT mode) =="
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli ptt \
	  --mode stream \
	  --log-level DEBUG \
	  --capture device=wm8960_in sample_rate=16000 channels=2 \
	  --playback device=wm8960_out

# ───────────────────────────────────────────────
# LCD HARD (zachowany wariant z poprawnym $$)
.PHONY: lcd-on-hard lcd-off-hard
lcd-on-hard:
	@BL=$${FACE_LCD_BL_PIN:-13}; AH=$${FACE_LCD_BL_ACTIVE_HIGH:-1}; DC=$${FACE_LCD_DC_PIN:-25}; RST=$${FACE_LCD_RST_PIN:-27}; DEV=$${FACE_LCD_SPI_DEV:-/dev/spidev0.0}; HZ=$${FACE_LCD_SPI_HZ:-$(FACE_LCD_SPI_HZ)}; \
	echo "[lcd-on-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"; \
	$(SUDO) -E $(PY) $(ROOT)/scripts/sys_lcd-control.py on --bl $$BL --bl-ah $$AH --dc $$DC --rst $$RST --spi $$DEV --hz $$HZ; \
	if [ "$$AH" = "1" ]; then sudo raspi-gpio set $$BL op dh; else sudo raspi-gpio set $$BL op dl; fi; \
	echo "BL pin=$$BL"; raspi-gpio get $$BL

lcd-off-hard:
	@BL=$${FACE_LCD_BL_PIN:-13}; AH=$${FACE_LCD_BL_ACTIVE_HIGH:-1}; DC=$${FACE_LCD_DC_PIN:-25}; RST=$${FACE_LCD_RST_PIN:-27}; DEV=$${FACE_LCD_SPI_DEV:-/dev/spidev0.0}; HZ=$${FACE_LCD_SPI_HZ:-$(FACE_LCD_SPI_HZ)}; \
	echo "[lcd-off-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"; \
	$(SUDO) -E $(PY) $(ROOT)/scripts/sys_lcd-control.py off --bl $$BL --bl-ah $$AH --dc $$DC --rst $$RST --spi $$DEV --hz $$HZ; \
	if [ "$$AH" = "1" ]; then sudo raspi-gpio set $$BL op dl; else sudo raspi-gpio set $$BL op dh; fi; \
	echo "BL pin=$$BL"; raspi-gpio get $$BL

# ───────────────────────────────────────────────
# TESTS & BENCH
.PHONY: test bench
test:
	@echo "Testy Rider-Pi..."
	@(pytest -q tests 2>/dev/null || $(PY) -m unittest discover -s tests -p "test_*.py" || true)

bench:
	bash scripts/diag_bench-detect.sh 10

# ───────────────────────────────────────────────
# CLEAN & TREE
.PHONY: clean tree
clean:
	@echo "Czyszczę cache i śmieci..."
	find . -type d \( -name "__pycache__" -o -name ".pytest_cache" \) -exec rm -rf {} + 2>/dev/null || true
	find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*~" -o -name "*.swp" -o -name "*.swo" -o -name "*.tmp" \) -delete 2>/dev/null || true

tree:
	@command -v tree >/dev/null 2>&1 && tree -a -I ".git" || find . -path "./.git" -prune -o -print

# ───────────────────────────────────────────────
# HEALTH CHECK (API na 8080)
.PHONY: health
health:
	@curl -fsS http://127.0.0.1:8080/healthz && echo || true

# Agent targets (do not remove)
-include config/agent/Makefile.agent

# ───────────────────────────────────────────────
# SYSTEMD SYNC
.PHONY: systemd-sync
systemd-sync:
	bash scripts/systemd-sync.sh
