# Rider-Pi — język poleceń
# użycie: make <komenda>  (alias: robot <komenda> jeśli masz alias)
PY      ?= /usr/bin/python3
SUDO    ?= sudo
ROOT    ?= $(CURDIR)
# All worktrees reuse the primary checkout's existing WSL virtualenv.
TEST_PY ?= $(abspath $(shell git rev-parse --git-common-dir)/..)/.venv/bin/python
TEST_ARGS ?= -q

# Domyślne LCD ENV (możesz nadpisać przy wywołaniu: FACE_LCD_ROTATE=270 make lcd-on)
FACE_LCD_ROTATE ?= 270
FACE_LCD_SPI_HZ ?= 32000000

# Aktualny zestaw usług (repo-first systemd)
SYSTEMD_SERVICES = $(filter-out rider-splash.service rider-wifi-unblock.service,$(notdir $(wildcard $(ROOT)/systemd/*.service)))

# Provider wyboru backendu głosowego:
# - openai (domyślnie)
# - local  (voice-web na :8092, config/voice_local_file.toml)
# Google/Gemini SDK jest wyłączone; wybór google/gemini zwraca błąd.
PROVIDER ?= openai  # allowed: openai, local

# VOICE (serwer www + CLI; opcjonalne VOICE_ARGS, np. ' --lang pl ')
VOICE_BIND ?= 127.0.0.1:8092

# Dziedziczenie kluczy z ~/.bash_profile do komend voice-* (+ opcjonalne wygaszenie szumu logów gRPC)
ENV_FROM_BASH = OPENAI_API_KEY="$$(bash -lc 'source ~/.bash_profile >/dev/null 2>&1; printf %s "$$OPENAI_API_KEY"')" \
                GRPC_VERBOSITY=ERROR GLOG_minloglevel=3 PYTHONWARNINGS="ignore:Field name .*Operation"

# Wybór pliku konfiguracyjnego dla trybu FILE zależnie od PROVIDER
ifeq ($(PROVIDER),local)
VOICE_FILE_CFG := ./config/voice.toml
else
VOICE_FILE_CFG := ./config/voice_openai_file.toml
endif

# Wybór pliku konfiguracyjnego dla STREAMING:
# Dla PROVIDER=local nie ma natywnego realtime WS — użyj wariantów file-based.
VOICE_STREAM_CFG := ./config/voice_openai_streaming.toml
ifneq ($(filter google gemini,$(PROVIDER)),)
$(error Google/Gemini SDK integration is disabled; use PROVIDER=local or PROVIDER=openai)
endif

# ───────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "Rider-Pi — język projektu"
	@echo ""
	@echo "═══ System Services ═══"
	@echo "  make broker           # uruchom brokera (foreground)"
	@echo "  make api              # uruchom API (foreground)"
	@echo "  make up               # restart broker+api (systemd)"
	@echo "  make stop-all         # zatrzymaj wszystkie usługi Rider-Pi"
	@echo "  make safemode         # zatrzaśnij E-Stop i wymagaj ACK wykonawcy"
	@echo ""
	@echo "═══ System Status & Logs ═══"
	@echo "  make status           # stan usług aplikacji i bramy ruchu"
	@echo "  make safety-status    # tylko odczyt stanu bramy, bez SDK"
	@echo "  make status-all       # status wszystkich usług rider-*"
	@echo "  make logs-broker      # logi brokera"
	@echo "  make logs-api         # logi API"
	@echo "  make logs-preview     # logi cam-preview"
	@echo "  make logs-all         # logi wszystkich kluczowych"
	@echo "  make logs-clean       # wyczyść logi journalctl dla rider-*"
	@echo ""
	@echo "═══ Voice (File-based) ═══"
	@echo "  make voice-file-listen [PROVIDER=openai|local]   # nasłuch ciągły (listen)"
	@echo "  make voice-file-ptt    [PROVIDER=openai|local]   # push-to-talk (ptt)"
	@echo "  make voice-file-once   [PROVIDER=openai|local]   # pojedyncza interakcja (once)"
	@echo "  make voice-asr-file FILE=path.wav                       # rozpoznaj mowę z pliku"
	@echo "  make voice-tts TEXT='Hello'                             # synteza + odtworzenie"
	@echo "  make voice-web                                           # uruchom serwer web UI (bind: $(VOICE_BIND))"
	@echo ""
	@echo "═══ Voice (Streaming WebSocket) ═══"
	@echo "  make voice-stream-once   [PROVIDER=openai] # pojedyncza interakcja (realtime WS)"
	@echo "  make voice-stream-listen [PROVIDER=openai] # nasłuch ciągły (realtime WS)"
	@echo "      * Uwaga: PROVIDER=local nie obsługuje realtime WS — użyj wariantów file-based."
	@echo "  make voice-kill       # zabij procesy głosowe/audio"
	@echo "  make voice-diag       # diagnostyka systemu"
	@echo "  make voice-smoke      # testy podstawowe (bez audio/sieci)"
	@echo ""
	@echo "═══ Camera Preview ═══"
	@echo "  make preview-run      # podgląd kamery (interactive, bez systemd)"
	@echo "  make preview-on       # start cam-preview (systemd)"
	@echo "  make preview-off      # stop  cam-preview (systemd)"
	@echo "  make preview-status   # status cam-preview"
	@echo ""
	@echo "═══ Vision Dispatcher ═══"
	@echo "  make vision-on        # start vision (dispatcher)"
	@echo "  make vision-off       # stop vision"
	@echo "  make vision-burst     # vision na czas (SECONDS=120 domyślnie)"
	@echo "  make vision-status    # status vision"
	@echo ""
	@echo "═══ Hardware Control — LCD ═══"
	@echo "  make lcd-on           # włącz LCD (wake + DISP_ON)"
	@echo "  make lcd-off          # wyłącz LCD (black + SLEEP, + próba BL)"
	@echo "  make lcd-reset        # alias ponownego ekranu startowego"
	@echo "  make lcd-black        # alias wyłączenia LCD"
	@echo "  make lcd-on-hard      # alias wspólnej obsługi LCD"
	@echo "  make lcd-off-hard     # alias wspólnego wygaszenia LCD"
	@echo ""
	@echo "═══ Hardware Control — LED ═══"
	@echo "  make led-on           # włącz LED"
	@echo "  make led-off          # wyłącz LED"
	@echo "  make led-blink        # miganie LED (HZ=2 lub ON=200 OFF=200)"
	@echo "  make led-status       # status LED"
	@echo "  make led-auto         # automatyczny tryb LED"
	@echo ""
	@echo "═══ Google Feed (bridge → cache → API) ═══"
	@echo "  make google-on        # start Google feed worker (systemd)"
	@echo "  make google-off       # stop Google feed worker"
	@echo "  make google-status    # status Google feed + cache files"
	@echo "  make google-logs      # logs Google feed worker"
	@echo ""
	@echo "═══ Face Rendering ═══"
	@echo "  make face-direct      # bezpośredni renderer LCD (scripts/dev_face-lcd-direct.py)"
	@echo "  make face-api-png     # render PNG przez face_api → /tmp/face_api.png)"
	@echo "  make face-api-lcd     # jednorazowy push na LCD przez face_api"
	@echo "  make face-testcard    # plansza testowa na LCD"
	@echo "  make face-bench       # krótki benchmark FPS"
	@echo ""
	@echo "═══ Configuration ═══"
	@echo "  make config-init      # inicjalizuj pliki konfiguracyjne z szablonów"
	@echo "  make config-edit-stream [PROVIDER=openai]   # edytuj streaming cfg"
	@echo "  make config-edit-file   [PROVIDER=openai|local] # edytuj file cfg"
	@echo ""
	@echo "═══ Diagnostics & Utilities ═══"
	@echo "  make pi-preview       # podgląd lokalnego commitu na Pi przed GitHubem"
	@echo "  make pi-preview-status # wersja i stan podglądu Pi"
	@echo "  make pi-rollback      # powrót z podglądu do poprzedniego main"
	@echo "  make pi-release PI_COMMIT=<sha> # wdrożenie zrecenzowanego main z GH"
	@echo "  make bus-spy          # podsłuch magistrali"
	@echo "  make test             # testy"
	@echo "  make bench            # benchmark detekcji"
	@echo "  make clean            # sprzątanie cache"
	@echo "  make tree             # drzewo repo"
	@echo "  make health           # /healthz API (port 8080)"
	@echo ""

# ───────────────────────────────────────────────

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
.PHONY: up stop-all status status-all logs-broker logs-api logs-all logs-preview logs-clean
up:
	@$(SUDO) systemctl restart rider-broker.service rider-api.service

stop-all:
	@$(PY) $(ROOT)/scripts/sys_emergency-stop.py stop
	@$(SUDO) systemctl stop $(SYSTEMD_SERVICES)

status:
	@systemctl --no-pager show $(SYSTEMD_SERVICES) --property=Id,LoadState,ActiveState,SubState
	@$(MAKE) safety-status

.PHONY: safety-status
safety-status:
	@$(PY) $(ROOT)/scripts/sys_emergency-stop.py status

status-all:
	@$(MAKE) status

logs-broker:
	@journalctl -u rider-broker.service -n 120 --no-pager

logs-api:
	@journalctl -u rider-api.service -n 120 --no-pager

logs-preview:
	@journalctl -u camera-capture@raw.service -n 120 --no-pager || true

logs-all:
	@journalctl -u rider-broker.service -n 80 --no-pager
	@echo "───"
	@journalctl -u rider-api.service -n 80 --no-pager
	@echo "───"
	@journalctl -u rider-vision.service -n 80 --no-pager
	@echo "───"
	@journalctl -u camera-capture@raw.service -n 80 --no-pager || true

logs-clean:
	@echo "== Cleaning systemd logs for rider-* services =="
	@$(SUDO) journalctl --rotate || true
	@$(SUDO) journalctl --vacuum-time=1s --vacuum-size=1M -u rider-broker.service || true
	@$(SUDO) journalctl --vacuum-time=1s --vacuum-size=1M -u rider-api.service || true
	@$(SUDO) journalctl --vacuum-time=1s --vacuum-size=1M -u rider-vision.service || true
	@$(SUDO) journalctl --vacuum-time=1s --vacuum-size=1M -u camera-capture@raw.service || true
	@echo "Logs cleaned."

# ───────────────────────────────────────────────
# SAFE MODE
.PHONY: safemode face-kill lcd-off-safe
safemode:
	@$(PY) $(ROOT)/scripts/sys_emergency-stop.py on

# Stop the owned face runtime; never kill API or unrelated processes.
face-kill:
	@$(PY) $(ROOT)/scripts/resource_ctl.py face stop $(CONTROL_MODE)

# Display shutdown does not stop unrelated robot goals.
lcd-off-safe:
	@$(MAKE) lcd-off

# ───────────────────────────────────────────────
# OPS HELPERS
.PHONY: lcd-on lcd-off lcd-reset lcd-black vendor-kill vendir-kill
lcd-on:
	@$(PY) $(ROOT)/scripts/resource_ctl.py lcd on $(CONTROL_MODE)

# LCD aliases share board wiring, owner checks and guarded power control.
lcd-off:
	@$(PY) $(ROOT)/scripts/resource_ctl.py lcd off $(CONTROL_MODE)

lcd-reset:
	@$(PY) $(ROOT)/scripts/resource_ctl.py lcd on $(CONTROL_MODE)

lcd-black:
	@$(PY) $(ROOT)/scripts/resource_ctl.py lcd off $(CONTROL_MODE)

vendor-kill:
	@echo "== Ubijam procesy dostawcy kamery/LCD =="
	@$(SUDO) systemctl stop yahboom* || true
	@$(SUDO) systemctl stop rider-vendor* || true
	@$(SUDO) systemctl stop jupyter.service || true

# alias dla literówki
vendir-kill:
	@$(MAKE) vendor-kill

# ───────────────────────────────────────────────
# TOOLS / DIAG
.PHONY: preview-run bus-spy
preview-run:
	@$(PY) $(ROOT)/scripts/robot_ctl.py start s2_camera_preview --seconds $${SECS:-120} $(CONTROL_MODE)

bus-spy:
	$(PY) scripts/diag_bus-spy.py

# ───────────────────────────────────────────────
# CAM PREVIEW (systemd on-demand)
.PHONY: preview-on preview-off preview-status
preview-on:
	@$(PY) $(ROOT)/scripts/robot_ctl.py start s2_camera_preview $(CONTROL_MODE)

preview-off:
	@$(PY) $(ROOT)/scripts/robot_ctl.py stop s2_camera_preview $(CONTROL_MODE)

preview-status:
	@$(PY) $(ROOT)/scripts/robot_ctl.py status s2_camera_preview $(CONTROL_MODE)

# ───────────────────────────────────────────────
# VISION CONTROL
.PHONY: vision-on vision-off vision-burst vision-status
vision-on:
	@$(PY) $(ROOT)/scripts/robot_ctl.py start s7_obstacle_module $(CONTROL_MODE)

vision-off:
	@$(PY) $(ROOT)/scripts/robot_ctl.py stop s7_obstacle_module $(CONTROL_MODE)

vision-burst:
	@$(PY) $(ROOT)/scripts/robot_ctl.py start s7_obstacle_module $(CONTROL_MODE) --seconds $(or $(SECONDS),120)

vision-status:
	@$(PY) $(ROOT)/scripts/robot_ctl.py status s7_obstacle_module $(CONTROL_MODE)

# ───────────────────────────────────────────────
# LED CONTROL
.PHONY: led-on led-off led-blink led-status led-auto
led-on:
	@$(PY) $(ROOT)/scripts/sys_led-control.py on $(CONTROL_MODE)

led-off:
	@$(PY) $(ROOT)/scripts/sys_led-control.py off $(CONTROL_MODE)

# Użycie: make led-blink HZ=2  (albo ON=200 OFF=200)
led-blink:
	@$(PY) $(ROOT)/scripts/sys_led-control.py blink --hz $(or $(HZ),2) $(if $(ON),--on-ms $(ON),) $(if $(OFF),--off-ms $(OFF),) $(CONTROL_MODE)

led-status:
	@$(PY) $(ROOT)/scripts/sys_led-control.py status $(CONTROL_MODE)

led-auto:
	@$(PY) $(ROOT)/scripts/sys_led-control.py auto $(CONTROL_MODE)

# ───────────────────────────────────────────────
# FACE (helpers)
.PHONY: face-direct face-api-png face-api-lcd face-testcard face-bench
# make face-direct EXPR=happy SECS=5 CONTROL_MODE=--direct
face-direct:
	@$(PY) $(ROOT)/scripts/resource_ctl.py face play $(CONTROL_MODE) --payload '{"expr":"$(or $(EXPR),happy)","sink":"lcd","duration_s":$(or $(SECS),5)}'

face-api-png:
	@echo "== Face API → PNG (/tmp/face_api.png) =="
	@ROT=$(FACE_LCD_ROTATE) $(PY) -c 'import os; from services.api_core import face_api; print(face_api.render(backend="png", expr=os.getenv("EXPR","happy"), size=int(os.getenv("SIZE","240")), rotate=int(os.environ.get("ROT","270")), out="/tmp/face_api.png"))'

face-api-lcd:
	@$(PY) $(ROOT)/scripts/resource_ctl.py face play $(CONTROL_MODE) --payload '{"expr":"$(or $(EXPR),happy)","sink":"lcd","duration_s":$(or $(SECS),5)}'

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

# ───────────────────────────────────────────────
# CONFIG HELPERS
.PHONY: config-init config-edit-stream config-edit-file
config-init:
	@echo "== Initializing config files from templates =="
	@bash $(ROOT)/scripts/config-init.sh

config-edit-stream:
	@echo "== Editing voice streaming config (PROVIDER=$(PROVIDER)) =="
	@$${EDITOR:-nano} $(VOICE_STREAM_CFG)

config-edit-file:
	@echo "== Editing voice file config (PROVIDER=$(PROVIDER)) =="
	@$${EDITOR:-nano} $(VOICE_FILE_CFG)

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
# VOICE — FILE-BASED (WAV/PCM)
.PHONY: voice-file-listen voice-file-ptt voice-file-once voice-asr-file voice-tts voice-web
voice-file-listen:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli $(VOICE_ARGS) --config $(VOICE_FILE_CFG) listen

voice-file-ptt:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli $(VOICE_ARGS) --config $(VOICE_FILE_CFG) ptt

voice-file-once:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli $(VOICE_ARGS) --config $(VOICE_FILE_CFG) once

voice-asr-file:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli --config $(VOICE_FILE_CFG) asr --file "$(FILE)" $(VOICE_ARGS)

voice-tts:
	$(ENV_FROM_BASH) PYTHONPATH=$(ROOT) $(PY) -m apps.voice.cli --config $(VOICE_FILE_CFG) tts --text "$(TEXT)" --play $(VOICE_ARGS)

voice-web:
	$(ENV_FROM_BASH) \
	PIPER_MODEL_DIR=$(ROOT)/models/piper \
	VOSK_MODEL_DIR=$(ROOT)/models/vosk/vosk-model-small-pl-0.22 \
	ASR_BACKEND=vosk \
	$(PY) -m apps.voice.web --bind $(VOICE_BIND) $(VOICE_ARGS)



# ───────────────────────────────────────────────
# VOICE — STREAMING (WebSocket Realtime)
.PHONY: voice-stream-once voice-stream-listen voice-kill voice-diag voice-smoke
voice-stream-once:
	@echo "== Single streaming interaction (WebSocket realtime, PROVIDER=$(PROVIDER)) =="
	@if [ "$(PROVIDER)" = "local" ]; then echo "Streaming realtime nieobsługiwany dla PROVIDER=local — użyj voice-file-*"; exit 1; fi
	pasuspender -- \
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli $(VOICE_ARGS) --config $(VOICE_STREAM_CFG) once

voice-stream-listen:
	@echo "== Continuous streaming listen (WebSocket realtime, PROVIDER=$(PROVIDER)) =="
	@if [ "$(PROVIDER)" = "local" ]; then echo "Streaming realtime nieobsługiwany dla PROVIDER=local — użyj voice-file-*"; exit 1; fi
	pasuspender -- \
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli $(VOICE_ARGS) --config $(VOICE_STREAM_CFG) listen

voice-kill:
	@echo "== Killing voice/audio processes =="
	-@pkill -f "apps.voice.cli" 2>/dev/null || true
	-@pkill -f "arecord" 2>/dev/null || true
	-@pkill -f "aplay" 2>/dev/null || true

# Compatibility alias: voice-free redirects to voice-kill
voice-free: voice-kill

voice-diag:
	$(ENV_FROM_BASH) $(PY) -m apps.voice.cli diag --audio $(VOICE_ARGS)

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
# LCD compatibility aliases
.PHONY: lcd-on-hard lcd-off-hard
lcd-on-hard:
	@$(PY) $(ROOT)/scripts/resource_ctl.py lcd on $(CONTROL_MODE)

lcd-off-hard:
	@$(PY) $(ROOT)/scripts/resource_ctl.py lcd off $(CONTROL_MODE)

# ───────────────────────────────────────────────
# TESTS & BENCH
.PHONY: test bench
test:
	@test -x "$(TEST_PY)" || { echo "Missing Rider-Pi WSL venv; see docs/ENVIRONMENT_POLICY.md"; exit 1; }
	@echo "Izolowane testy programowe Rider-Pi; bez fizycznych aktuatorów..."
	@"$(TEST_PY)" -m pytest $(TEST_ARGS)

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
# GOOGLE FEED (bridge → cache → API)
.PHONY: google-on google-off google-status google-logs
google-on:
	@echo "== Starting Google Feed (rider-google-bridge.service) =="
	@$(SUDO) systemctl enable --now rider-google-bridge.service

google-off:
	@echo "== Stopping Google Feed (rider-google-bridge.service) =="
	@$(SUDO) systemctl disable --now rider-google-bridge.service

google-status:
	@echo "== Google Feed Status =="
	@$(SUDO) systemctl status rider-google-bridge.service --no-pager || true
	@echo ""
	@echo "== Cache files =="
	@ls -lh $(ROOT)/data/google/ 2>/dev/null || echo "No cache files yet"

google-logs:
	@echo "== Google Feed Logs =="
	@$(SUDO) journalctl -u rider-google-bridge.service -fn 50 --no-pager

# ───────────────────────────────────────────────
# HEALTH CHECK (API na 8080)
.PHONY: health
health:
	@curl -fsS http://127.0.0.1:8080/healthz

# Agent targets (do not remove)
-include config/agent/Makefile.agent

.PHONY: test-env lint
test-env:
	@test -x "$(TEST_PY)" || { echo "Missing Rider-Pi WSL venv; see docs/ENVIRONMENT_POLICY.md"; exit 1; }
	"$(TEST_PY)" -m pip check
	"$(TEST_PY)" -m ruff --version

lint:
	@test -x "$(TEST_PY)" || { echo "Missing Rider-Pi WSL venv; see docs/ENVIRONMENT_POLICY.md"; exit 1; }
	"$(TEST_PY)" -m ruff check .
	"$(TEST_PY)" -m ruff format --check .

# ───────────────────────────────────────────────
# SYSTEMD SYNC
.PHONY: systemd-sync
systemd-sync:
	bash scripts/systemd-sync.sh

# Deployment runs from WSL and uses only Python's standard library, Git and SSH.
PI_DEPLOY_ARGS ?=
.PHONY: pi-preview pi-preview-status pi-rollback pi-release
pi-preview:
	$(PY) scripts/dev_pi-deploy.py preview $(PI_DEPLOY_ARGS)

pi-preview-status:
	$(PY) scripts/dev_pi-deploy.py status $(PI_DEPLOY_ARGS)

pi-rollback:
	$(PY) scripts/dev_pi-deploy.py rollback $(PI_DEPLOY_ARGS)

pi-release:
	@test -n "$(PI_COMMIT)" || { echo "Podaj PI_COMMIT: pełny hash main po merge PR."; exit 1; }
	$(PY) scripts/dev_pi-deploy.py release --commit "$(PI_COMMIT)" $(PI_DEPLOY_ARGS)

# Public controls: CONTROL_MODE=--direct for local operation while API is stopped.
.PHONY: goal-on goal-off goals
goal-on:
	@$(PY) $(ROOT)/scripts/robot_ctl.py start $(GOAL) $(CONTROL_MODE)
goal-off:
	@$(PY) $(ROOT)/scripts/robot_ctl.py stop $(GOAL) $(CONTROL_MODE)
goals:
	@$(PY) $(ROOT)/scripts/robot_ctl.py status $(CONTROL_MODE)
