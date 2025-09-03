# Rider-Pi — język poleceń
# użycie: robot <komenda>

PY      ?= /usr/bin/python3
SUDO    ?= sudo
ROOT    ?= $(CURDIR)

SYSTEMD_SERVICES = rider-broker.service rider-api.service rider-dispatcher.service rider-menu.service rider-motion.service rider-ui-manager.service

# ───────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "Rider-Pi — język projektu"
	@echo "  robot broker        # uruchom brokera (foreground)"
	@echo "  robot api           # uruchom API (foreground)"
	@echo "  robot stop-all      # zatrzymaj wszystkie usługi systemowe"
	@echo "  robot safemode      # tryb awaryjny (kill + stop + LCD off)"
	@echo "  robot lcd-on        # włącz LCD (ops/lcdctl.py on)"
	@echo "  robot lcd-off       # zgaś LCD (ops/lcdctl.py off)"
	@echo "  robot lcd-status    # status LCD (ops/lcdctl.py status)"
	@echo "  robot vendor-kill   # ubij procesy dostawcy kamery/LCD"
	@echo "  robot preview-ssd   # podgląd kamery SSD"
	@echo "  robot bus-spy       # podsłuch magistrali"
	@echo "  robot vision-on     # uruchom usługę vision"
	@echo "  robot vision-off    # zatrzymaj usługę vision"
	@echo "  robot vision-burst  # uruchom vision na czas (domyślnie 120s)"
	@echo "  robot vision-status # status usługi vision"
	@echo "  robot led-on        # włącz diodę statusową (sysfs)"
	@echo "  robot led-off       # zgaś diodę statusową"
	@echo "  robot led-blink     # miganie diody (HZ=2 lub ON/OFF w ms)"
	@echo "  robot led-status    # pokaż trigger/brightness"
	@echo "  robot led-auto      # przywróć domyślny trigger LED (np. mmc0)"
	@echo "  robot test          # uruchom testy"
	@echo "  robot bench         # benchmark detekcji"
	@echo "  robot clean         # usuń cache i śmieci"
	@echo "  robot tree          # pokaż drzewo repo"
	@echo ""

# ───────────────────────────────────────────────
# DEV RUN
broker:
	-@sudo fuser -k 5555/tcp 5556/tcp 2>/dev/null || true
	$(PY) services/broker.py

api:
	$(PY) services/status_api.py

# ───────────────────────────────────────────────
# SYSTEMD
stop-all:
	-$(SUDO) systemctl stop $(SYSTEMD_SERVICES)

# ───────────────────────────────────────────────
# SAFE MODE
safemode:
	-$(SUDO) $(ROOT)/ops/camera_takeover_kill.sh
	-$(SUDO) systemctl stop $(SYSTEMD_SERVICES)
	-$(SUDO) $(PY) $(ROOT)/ops/lcdctl.py off --no-spi || true
	-$(SUDO) $(PY) $(ROOT)/ops/ledctl.py off || true

# ───────────────────────────────────────────────
# OPS HELPERS
.PHONY: lcd-on lcd-off lcd-status vendor-kill

lcd-on:
	@echo "== Włączam LCD (wyjście ze snu) =="
	@$(SUDO) $(PY) $(ROOT)/ops/lcdctl.py on || true

lcd-off:
	@echo "== Wyłączam LCD (uśpienie panelu) =="
	@$(SUDO) $(PY) $(ROOT)/ops/lcdctl.py off || true

lcd-status:
	@$(SUDO) $(PY) $(ROOT)/ops/lcdctl.py status || true

vendor-kill:
	@echo "== Ubijam procesy dostawcy kamery/LCD =="
	@$(SUDO) bash $(ROOT)/ops/camera_takeover_kill.sh || true

# ───────────────────────────────────────────────
# TOOLS / DIAG
preview-ssd:
	@echo "Podgląd SSD (Ctrl+C aby zakończyć)..."
	$(PY) apps/camera/preview_lcd_ssd.py

bus-spy:
	$(PY) tools/bus_spy.py

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
	@$(SUDO) $(PY) $(ROOT)/ops/ledctl.py on

led-off:
	@echo "== LED OFF =="
	@$(SUDO) $(PY) $(ROOT)/ops/ledctl.py off

# Użycie: make led-blink HZ=2  (albo ON=200 OFF=200)
led-blink:
	@echo "== LED BLINK =="
	@if [ -n "$(HZ)" ]; then \
		$(SUDO) $(PY) $(ROOT)/ops/ledctl.py blink --hz $(HZ); \
	else \
		$(SUDO) $(PY) $(ROOT)/ops/ledctl.py blink --on-ms $${ON:-200} --off-ms $${OFF:-200}; \
	fi

led-status:
	@$(SUDO) $(PY) $(ROOT)/ops/ledctl.py status

led-auto:
	@echo "== LED AUTO =="
	@$(SUDO) $(PY) $(ROOT)/ops/ledctl.py auto

# ───────────────────────────────────────────────
# TESTS & BENCH
test:
	@echo "Testy Rider-Pi..."
	@(pytest -q tests 2>/dev/null || $(PY) -m unittest discover -s tests -p "test_*.py" || true)

bench:
	bash ops/bench_detect.sh 10

# ───────────────────────────────────────────────
# CLEAN & TREE
clean:
	@echo "Czyszczę cache i śmieci..."
	find . -type d \( -name "__pycache__" -o -name ".pytest_cache" \) -exec rm -rf {} + 2>/dev/null || true
	find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*~" -o -name "*.swp" -o -name "*.swo" -o -name "*.tmp" \) -delete 2>/dev/null || true

tree:
	@command -v tree >/dev/null 2>&1 && tree -a -I ".git" || find . -path "./.git" -prune -o -print

# ───────────────────────────────────────────────
# HEALTH CHECK
.PHONY: health
health:
	@curl -fsS http://127.0.0.1:8080/health  || curl -fsS http://127.0.0.1:8080/healthz
	@echo

# ───────────────────────────────────────────────
# systemd helpers
.PHONY: up down status status-all logs logs-broker logs-api enable disable

up:
	@sudo systemctl restart rider-broker.service rider-api.service
status:
	@systemctl --no-pager --full status rider-broker.service | sed -n '1,20p'
	@systemctl --no-pager --full status rider-api.service    | sed -n '1,20p'
logs-broker:
	@journalctl -u rider-broker.service -n 120 --no-pager
logs-api:
	@journalctl -u rider-api.service -n 120 --no-pager
