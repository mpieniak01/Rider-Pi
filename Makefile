# Rider-Pi — język poleceń
# użycie: make <komenda>  (alias: robot <komenda> jeśli masz alias)
PY      ?= /usr/bin/python3
SUDO    ?= sudo
ROOT    ?= $(CURDIR)

# Aktualny zestaw usług (repo-first systemd)
SYSTEMD_SERVICES = rider-broker.service rider-api.service rider-vision.service rider-ssd-preview.service

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
	@echo "  make logs-ssd         # logi SSD preview"
	@echo "  make logs-all         # logi wszystkich kluczowych"
	@echo ""
	@echo "  make stop-all         # zatrzymaj wszystkie usługi Rider-Pi"
	@echo "  make safemode         # tryb awaryjny (kill vendor, stop, LCD off, LED off)"
	@echo ""
	@echo "  make preview-ssd      # podgląd kamery SSD (interactive)"
	@echo "  make ssd-on           # start SSD preview (systemd)"
	@echo "  make ssd-off          # stop  SSD preview (systemd)"
	@echo "  make ssd-status       # status SSD preview"
	@echo ""
	@echo "  make bus-spy          # podsłuch magistrali"
	@echo ""
	@echo "  make vision-on        # start vision (dispatcher)"
	@echo "  make vision-off       # stop vision"
	@echo "  make vision-burst     # vision na czas (SECONDS=120 domyślnie)"
	@echo "  make vision-status    # status vision"
	@echo ""
	@echo "  make lcd-on           # włącz LCD"
	@echo "  make lcd-off          # wyłącz LCD (sleep)"
	@echo "  make lcd-status       # status LCD"
	@echo "  make vendor-kill      # ubij vendorowe procesy kamery/LCD"
	@echo ""
	@echo "  make x-on             # włącz środowisko graficzne + RealVNC (X11, :5900)"
	@echo "  make x-off            # wyłącz środowisko graficzne (powrót do multi-user)"
	@echo "  make vnc-virtual-on   # uruchom wirtualny VNC (:5901) bez X11"
	@echo "  make vnc-virtual-off  # wyłącz wirtualny VNC"
	@echo "  make gfx-status       # status lightdm / vnc"
	@echo ""
	@echo "  make test             # testy"
	@echo "  make bench            # benchmark detekcji"
	@echo "  make clean            # sprzątanie cache"
	@echo "  make tree             # drzewo repo"
	@echo "  make health           # /healthz API (port 5000)"
	@echo ""

# ───────────────────────────────────────────────
# DEV RUN (foreground)
.PHONY: broker api
broker:
	-@sudo fuser -k 5555/tcp 5556/tcp 2>/dev/null || true
	$(PY) services/broker.py

api:
	$(PY) services/status_api.py

# ───────────────────────────────────────────────
# SYSTEMD
.PHONY: up stop-all status status-all logs-broker logs-api logs-all
up:
	@$(SUDO) systemctl restart rider-broker.service rider-api.service

stop-all:
	-$(SUDO) systemctl stop $(SYSTEMD_SERVICES)

status:
	@systemctl --no-pager --full status rider-broker.service | sed -n '1,20p'
	@systemctl --no-pager --full status rider-api.service    | sed -n '1,20p'
	@systemctl --no-pager --full status rider-vision.service | sed -n '1,20p'

status-all:
	@systemctl list-units --type=service --all | grep -E 'rider-(broker|api|vision|ssd-preview)'

logs-broker:
	@journalctl -u rider-broker.service -n 120 --no-pager

logs-api:
	@journalctl -u rider-api.service -n 120 --no-pager

logs-all:
	@journalctl -u rider-broker.service -n 80 --no-pager
	@echo "───"
	@journalctl -u rider-api.service -n 80 --no-pager
	@echo "───"
	@journalctl -u rider-vision.service -n 80 --no-pager
	@echo "───"
	@journalctl -u rider-ssd-preview.service -n 80 --no-pager || true

# ───────────────────────────────────────────────
# SAFE MODE
.PHONY: safemode
safemode:
	-$(SUDO) $(ROOT)/ops/camera_takeover_kill.sh
	-$(SUDO) systemctl stop $(SYSTEMD_SERVICES)
	-$(SUDO) $(PY) $(ROOT)/scripts/lcdctl.py off --no-spi || true
	-$(SUDO) $(PY) $(ROOT)/ops/ledctl.py off || true

# ───────────────────────────────────────────────
# OPS HELPERS
.PHONY: lcd-on lcd-off lcd-status vendor-kill
lcd-on:
	@echo "== Włączam LCD (wyjście ze snu) =="
	@$(SUDO) $(PY) $(ROOT)/scripts/lcdctl.py on || true

lcd-off:
	@echo "== Wyłączam LCD (uśpienie panelu) =="
	@$(SUDO) $(PY) $(ROOT)/scripts/lcdctl.py off || true

lcd-status:
	@$(SUDO) $(PY) $(ROOT)/scripts/lcdctl.py status || true

vendor-kill:
	@echo "== Ubijam procesy dostawcy kamery/LCD =="
	@$(SUDO) bash $(ROOT)/ops/camera_takeover_kill.sh || true

# ───────────────────────────────────────────────
# TOOLS / DIAG
.PHONY: preview-ssd bus-spy
preview-ssd:
	@echo "Podgląd SSD (Ctrl+C aby zakończyć)..."
	$(PY) apps/camera/preview_lcd_ssd.py

bus-spy:
	$(PY) tools/bus_spy.py

# ───────────────────────────────────────────────
# SSD PREVIEW (systemd on-demand)
.PHONY: ssd-on ssd-off ssd-status logs-ssd
ssd-on:
	@$(SUDO) systemctl start rider-ssd-preview.service

ssd-off:
	@$(SUDO) systemctl stop rider-ssd-preview.service || true

ssd-status:
	@systemctl --no-pager --full status rider-ssd-preview.service | sed -n '1,20p' || true

logs-ssd:
	@journalctl -u rider-ssd-preview.service -n 120 --no-pager || true

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
# ŚRODOWISKO GRAFICZNE / REALVNC
# :5900 = vncserver-x11-serviced (wymaga lightdm/gdm3)
# :5901 = vncserver-virtuald (wirtualny pulpit, bez X11)
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
# HEALTH CHECK (API na 5000)
.PHONY: health
health:
	@curl -fsS http://127.0.0.1:5000/healthz && echo || true
