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
	@echo "  make lcd-off          # wyłącz LCD (DISP_OFF + sleep)"
	@echo "  make lcd-reset        # panel reset (RST) + ON"
	@echo "  make lcd-black        # wyczyść ekran do czerni (presenter)"
	@echo ""
	@echo "  make face-direct      # bezpośredni renderer LCD (tools/newface_lcd_direct.py)"
	@echo "                         #   EXPR=happy FPS=20 SECS=5 FORCE=rgb565_3"
	@echo "  make face-api-png     # render PNG przez face_api → /tmp/face_api.png"
	@echo "  make face-api-lcd     # jednorazowy push na LCD przez face_api"
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
	@systemctl restart rider-broker.service rider-api.service

stop-all:
	-@systemctl stop $(SYSTEMD_SERVICES)

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
.PHONY: safemode
safemode:
	-@$(ROOT)/ops/camera_takeover_kill.sh || true
	-@systemctl stop $(SYSTEMD_SERVICES)
	-@$(SUDO) $(PY) $(ROOT)/tools/lcdctl.py off || true
	-@$(PY) $(ROOT)/ops/ledctl.py off || true

# ───────────────────────────────────────────────
# OPS HELPERS
.PHONY: lcd-on lcd-off lcd-reset lcd-black vendor-kill
lcd-on:
	@echo "== Włączam LCD (wyjście ze snu) =="
	@FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) $(SUDO) $(PY) $(ROOT)/tools/lcdctl.py on || true

lcd-off:
	@echo "== Wyłączam LCD (uśpienie panelu) =="
	@FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) $(SUDO) $(PY) $(ROOT)/tools/lcdctl.py off || true

lcd-reset:
	@echo "== RESET panelu LCD =="
	@FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) $(SUDO) $(PY) $(ROOT)/tools/lcdctl.py reset || true

lcd-black:
	@$(PY) $(ROOT)/tools/lcd_presenter_clear.py

vendor-kill:
	@echo "== Ubijam procesy dostawcy kamery/LCD =="
	@sudo systemctl stop yahboom* || true
	@sudo systemctl stop rider-vendor* || true
	@sudo systemctl stop jupyter.service || true
	@sudo systemctl start jupyter.service || true

# ───────────────────────────────────────────────
# TOOLS / DIAG
.PHONY: preview-run bus-spy
preview-run:
	@echo "Podgląd (Ctrl+C aby zakończyć)..."
	$(PY) -u apps/camera/preview_lcd.py

bus-spy:
	$(PY) tools/bus_spy.py

# ───────────────────────────────────────────────
# CAM PREVIEW (systemd on-demand) + aliasy wsteczne
.PHONY: preview-on preview-off preview-status
preview-on:
	@systemctl start rider-cam-preview.service

preview-off:
	@systemctl stop rider-cam-preview.service || true

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
	@$(ROOT)/ops/vision_ctl.sh on

vision-off:
	@echo "== Vision OFF =="
	@$(ROOT)/ops/vision_ctl.sh off

vision-burst:
	@echo "== Vision BURST ($(or $(SECONDS),120)s) =="
	@$(ROOT)/ops/vision_ctl.sh burst $(or $(SECONDS),120)

vision-status:
	@$(ROOT)/ops/vision_ctl.sh status

# ───────────────────────────────────────────────
# LED CONTROL
.PHONY: led-on led-off led-blink led-status led-auto
led-on:
	@echo "== LED ON =="
	@$(PY) $(ROOT)/ops/ledctl.py on

led-off:
	@echo "== LED OFF =="
	@$(PY) $(ROOT)/ops/ledctl.py off

# Użycie: make led-blink HZ=2  (albo ON=200 OFF=200)
led-blink:
	@echo "== LED BLINK =="
	@if [ -n "$(HZ)" ]; then \
		$(PY) $(ROOT)/ops/ledctl.py blink --hz $(HZ); \
	else \
		$(PY) $(ROOT)/ops/ledctl.py blink --on-ms $${ON:-200} --off-ms $${OFF:-200}; \
	fi

led-status:
	@$(PY) $(ROOT)/ops/ledctl.py status

led-auto:
	@echo "== LED AUTO =="
	@$(PY) $(ROOT)/ops/ledctl.py auto

# ───────────────────────────────────────────────
# FACE (helpers)
.PHONY: face-direct face-api-png face-api-lcd
# make face-direct EXPR=happy FPS=20 SECS=5 FORCE=rgb565_3
face-direct:
	@echo "== Face direct (tools/newface_lcd_direct.py) =="
	@FACE_LCD_ROTATE=$(FACE_LCD_ROTATE) FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) \
	$(SUDO) -E $(PY) $(ROOT)/tools/newface_lcd_direct.py \
		--expr $${EXPR:-neutral} --rotate $(FACE_LCD_ROTATE) --spi-hz $(FACE_LCD_SPI_HZ) \
		--fps $${FPS:-20} $${FORCE:+--force $${FORCE}} $${SECS:+--secs $${SECS}} --stats

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
# TESTS & BENCH
.PHONY: test bench
test:
	@echo "Testy Rider-Pi..."
	@(pytest -q tests 2>/dev/null || $(PY) -m unittest discover -s tests -p "test_*.py" || true)

bench:
	bash ops/bench_detect.sh 10

# ───────────────────────────────────────────────
# CLEAN & TREE
.PHONY: clean tree
clean:
	@echo "Czyszczę cache i śmieci..."
	find . -type d \( -name "__pycache__" -o -name ".pytest_cache" \) -exec rm -rf {} + 2>/dev/null || true
	find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*~" -o -name "*.swp" -o -name "*.swo" -o -name "*.tmp" \) -delete 2>/dev/null || true

tree:
	@command -v tree >/dev/null 21 && tree -a -I ".git" || find . -path "./.git" -prune -o -print

# ───────────────────────────────────────────────
# HEALTH CHECK (API na 8080)
.PHONY: health
health:
	@curl -fsS http://127.0.0.1:8080/healthz && echo || true

# Agent targets (do not remove)
-include ops/agent/Makefile.agent

.PHONY: face-testcard face-direct-raw face-api-lcd

.PHONY: face-api-lcd
face-api-lcd:
	@echo "== Face API → LCD (jedna klatka) =="
	@ROT=$(FACE_LCD_ROTATE) HZ=$(FACE_LCD_SPI_HZ) $(PY) -c 'import os; from services.api_core import face_api; print(face_api.render(backend="lcd", expr=os.getenv("EXPR","happy"), size=int(os.getenv("SIZE","240")), rotate=int(os.environ.get("ROT","270")), spi_hz=int(os.environ.get("HZ","32000000"))))'
face-direct-raw:
	@echo "== Face direct RAW (rgb565_3) =="
	@echo "[make] rotate=$(FACE_LCD_ROTATE) hz=$(FACE_LCD_SPI_HZ)"
	@FACE_LCD_ROTATE=$(FACE_LCD_ROTATE) FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) \
	$(SUDO) -E $(PY) $(ROOT)/tools/newface_lcd_direct.py \
	  --expr $${EXPR:-happy} --rotate $(FACE_LCD_ROTATE) --spi-hz $(FACE_LCD_SPI_HZ) \
	  --fps $${FPS:-20} --stats $${SECS:+--secs $${SECS}} --force push_frame:rgb565_3

.PHONY: face-testcard face-api-png


.PHONY: face-testcard face-api-png

face-testcard:
	@echo "== LCD testcard (kolorowe pasy) =="
	@FACE_LCD_SPI_HZ=$(FACE_LCD_SPI_HZ) $(SUDO) -E $(PY) $(ROOT)/tools/lcd_presenter_testcard.py --rotate $(FACE_LCD_ROTATE) --spi-hz $(FACE_LCD_SPI_HZ)

face-api-png:
	@echo "== Face API → PNG (/tmp/face_api.png) =="
	@ROT=$(FACE_LCD_ROTATE) $(PY) -c 'import os; from services.api_core import face_api; print(face_api.render(backend="png", expr=os.getenv("EXPR","happy"), size=int(os.getenv("SIZE","240")), rotate=int(os.environ.get("ROT","270")), out="/tmp/face_api.png"))'

# ───────────────────────────────────────────────
# FACE benchmark (krótki test FPS)
.PHONY: face-bench
face-bench:
	@echo "== FACE BENCH =="
	@for HZ in $${HZ_LIST:-32000000 48000000 64000000}; do \
		echo "--- HZ=$$HZ ROT=$(FACE_LCD_ROTATE) (secs=$${SECS:-4}) ---"; \
		FACE_LCD_ROTATE=$(FACE_LCD_ROTATE) FACE_LCD_SPI_HZ=$$HZ \
		$(SUDO) -E $(PY) $(ROOT)/tools/newface_lcd_direct.py \
		  --expr happy --rotate $(FACE_LCD_ROTATE) --spi-hz $$HZ \
		  --secs $${SECS:-4} --stats --force push_frame:rgb565_3 \
		  | sed -n '/^\[stats\]/p;/^\\[LCD] Statystyki/p'; \
	done
	@echo "Tip: możesz nadpisać:  HZ_LIST=\"32000000 48000000\"  oraz SECS=6"

.PHONY: lcd-recover
lcd-recover:
	-@$(MAKE) vendor-kill || true
	-@$(MAKE) preview-off || true
	-@$(MAKE) vision-off  || true
	-@$(MAKE) stop-all    || true
	-@$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py off   || true
	@sleep 0.2
	-@$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py reset || true
	@sleep 0.2
	-@$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py on    || true
	@$(PY) $(ROOT)/tools/lcd_presenter_clear.py      || true

.PHONY: lcd-on-hard lcd-off-hard lcd-reset-hard lcd-status

lcd-on-hard:
	@BL=$${FACE_LCD_BL_PIN:-13}; AH=$${FACE_LCD_BL_ACTIVE_HIGH:-1}; DC=$${FACE_LCD_DC_PIN:-25}; RST=$${FACE_LCD_RST_PIN:-27}; DEV=$${FACE_LCD_SPI_DEV:-/dev/spidev0.0}; HZ=$${FACE_LCD_SPI_HZ:-$(FACE_LCD_SPI_HZ)}; \
	@echo "[lcd-on-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"
	$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py on \
	  --bl $$BL --bl-ah $$AH --dc $$DC --rst $$RST --spi $$DEV --hz $$HZ

lcd-off-hard:
	@BL=$$${FACE_LCD_BL_PIN:-13}; AH=$$${FACE_LCD_BL_ACTIVE_HIGH:-1}; DC=$$${FACE_LCD_DC_PIN:-25}; RST=$$${FACE_LCD_RST_PIN:-27}; DEV=$$${FACE_LCD_SPI_DEV:-/dev/spidev0.0}; HZ=$$${FACE_LCD_SPI_HZ:-$(FACE_LCD_SPI_HZ)}; \
	@echo "[lcd-on-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"
	@echo "[lcd-off-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"
	$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py off \
	  --bl $$BL --bl-ah $$AH --dc $$DC --rst $$RST --spi $$DEV --hz $$HZ

lcd-reset-hard:
	@DC=$$$${FACE_LCD_DC_PIN:-25}; RST=$$$${FACE_LCD_RST_PIN:-27}; DEV=$$$${FACE_LCD_SPI_DEV:-/dev/spidev0.0}; HZ=$$$${FACE_LCD_SPI_HZ:-$(FACE_LCD_SPI_HZ)}; \
	@echo "[lcd-on-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"
	@echo "[lcd-off-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"
	$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py reset \
	  --dc $$DC --rst $$RST --spi $$DEV --hz $$HZ

lcd-status:
	@BL=$$$$${FACE_LCD_BL_PIN:-13}; echo "BL pin=$$BL"; raspi-gpio get $$BL || true
