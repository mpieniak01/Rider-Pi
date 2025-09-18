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


.PHONY: lcd-on-hard lcd-off-hard lcd-reset-hard lcd-status

lcd-on-hard:
	@BL=$${FACE_LCD_BL_PIN:-13}; AH=$${FACE_LCD_BL_ACTIVE_HIGH:-1}; DC=$${FACE_LCD_DC_PIN:-25}; RST=$${FACE_LCD_RST_PIN:-27}; DEV=$${FACE_LCD_SPI_DEV:-/dev/spidev0.0}; HZ=$${FACE_LCD_SPI_HZ:-$(FACE_LCD_SPI_HZ)}; \
	echo "[lcd-on-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"; \
	$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py on --bl $$BL --bl-ah $$AH --dc $$DC --rst $$RST --spi $$DEV --hz $$HZ; \
	if [ "$$AH" = "1" ]; then sudo raspi-gpio set $$BL op dh; else sudo raspi-gpio set $$BL op dl; fi; \
	echo "BL pin=$$BL"; raspi-gpio get $$BL

lcd-off-hard:
	@BL=$${FACE_LCD_BL_PIN:-13}; AH=$${FACE_LCD_BL_ACTIVE_HIGH:-1}; DC=$${FACE_LCD_DC_PIN:-25}; RST=$${FACE_LCD_RST_PIN:-27}; DEV=$${FACE_LCD_SPI_DEV:-/dev/spidev0.0}; HZ=$${FACE_LCD_SPI_HZ:-$(FACE_LCD_SPI_HZ)}; \
	echo "[lcd-off-hard] BL=$$BL AH=$$AH DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"; \
	$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py off --bl $$BL --bl-ah $$AH --dc $$DC --rst $$RST --spi $$DEV --hz $$HZ; \
	if [ "$$AH" = "1" ]; then sudo raspi-gpio set $$BL op dl; else sudo raspi-gpio set $$BL op dh; fi; \
	echo "BL pin=$$BL"; raspi-gpio get $$BL

lcd-reset-hard:
	@DC=$${FACE_LCD_DC_PIN:-25}; RST=$${FACE_LCD_RST_PIN:-27}; DEV=$${FACE_LCD_SPI_DEV:-/dev/spidev0.0}; HZ=$${FACE_LCD_SPI_HZ:-$(FACE_LCD_SPI_HZ)}; \
	echo "[lcd-reset-hard] DC=$$DC RST=$$RST SPI=$$DEV HZ=$$HZ"; \
	$(SUDO) -E $(PY) $(ROOT)/tools/lcdctl.py reset --dc $$DC --rst $$RST --spi $$DEV --hz $$HZ

lcd-status:
	@BL=$${FACE_LCD_BL_PIN:-13}; echo "BL pin=$$BL"; raspi-gpio get $$BL
