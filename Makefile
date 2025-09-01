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
	@echo "  robot preview-ssd   # podgląd kamery SSD"
	@echo "  robot bus-spy       # podsłuch magistrali"
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
	-$(SUDO) $(PY) $(ROOT)/ops/lcdctl.py off || true

# ───────────────────────────────────────────────
# TOOLS / DIAG
preview-ssd:
	@echo "Podgląd SSD (Ctrl+C aby zakończyć)..."
	$(PY) apps/camera/preview_lcd_ssd.py

bus-spy:
	$(PY) tools/bus_spy.py

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
