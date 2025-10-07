# Skrypty monitoringu (`ops/monitor_*.sh`)

## monitor_metrics.sh

### Opis

Monitoruje **metryki systemowe** — CPU, pamięć, temperatura, dysk, network.

### Użycie

```bash
./ops/monitor_metrics.sh [interval]
```

### Parametry

| Parametr | Typ | Domyślny | Opis |
|----------|-----|----------|------|
| `interval` | int | `5` | Interwał pomiarów (sekundy) |

### Zbierane metryki

⚠️ **Wymaga weryfikacji:** Lista metryk do uzupełnienia.

Prawdopodobnie:
- **CPU:** użycie (%), load average
- **RAM:** użyta/dostępna (MB), %
- **Temp:** temperatura CPU (°C)
- **Dysk:** użycie partycji (`/`, `/boot`)
- **Network:** RX/TX bytes/s
- **Procesy:** liczba, top użytkowników CPU

### Przykład output

```
[2025-01-07 12:30:00] CPU: 45% | RAM: 512/1024 MB (50%) | Temp: 52°C | Disk: 8.2/16 GB
[2025-01-07 12:30:05] CPU: 38% | RAM: 520/1024 MB (51%) | Temp: 51°C | Disk: 8.2/16 GB
```

### Output

⚠️ **Wymaga weryfikacji:** Format do uzupełnienia.

Możliwe formaty:
- `stdout` — plain text logs
- `JSON` — structured logging
- `CSV` — eksport do pliku
- BUS publish — `system.metrics` topic

### Przykłady

```bash
# Monitoruj co 10 sekund
./ops/monitor_metrics.sh 10

# Zapisz do pliku
./ops/monitor_metrics.sh 5 > metrics.log

# Monitor w tle
nohup ./ops/monitor_metrics.sh 30 &
```

### Integracja z systemd

```bash
# Jeśli skonfigurowane jako usługa
sudo systemctl start rider-metrics.service
journalctl -u rider-metrics.service -f
```

---

## monitor_stream.sh

### Opis

Monitoruje **strumienie danych** — topiki BUS, throughput, opóźnienia.

### Użycie

```bash
./ops/monitor_stream.sh [topic...]
```

### Parametry

| Parametr | Typ | Opis |
|----------|-----|------|
| `topic` | str... | Lista topiców do monitorowania (domyślnie: wszystkie) |

### Monitorowane aspekty

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

Prawdopodobnie:
- **Throughput:** wiadomości/s
- **Latency:** opóźnienie timestamp → odbiór
- **Queue size:** długość kolejki (Redis/ZMQ)
- **Drops:** utracone wiadomości

### Przykład output

```
[motion] 50 msg/s | latency: 12ms avg | queue: 0
[vision.state] 5 msg/s | latency: 45ms avg | queue: 2
[audio.transcript] 0.5 msg/s | latency: 150ms avg | queue: 0
```

### Przykłady

```bash
# Monitoruj wszystkie topiki
./ops/monitor_stream.sh

# Tylko motion i vision
./ops/monitor_stream.sh motion vision.state

# Eksport do CSV
./ops/monitor_stream.sh > stream_metrics.csv
```

---

## Diagnostyka metryk

### CPU/RAM/Temp (ręcznie)

```bash
# CPU load
uptime

# RAM
free -h

# Temperatura (RPi)
vcgencmd measure_temp

# Dysk
df -h

# Top processes
htop  # lub top
```

### Network (ręcznie)

```bash
# Interface stats
ifconfig

# Bandwidth
iftop  # wymaga instalacji

# Connections
netstat -tupn
```

### BUS metrics (ręcznie)

```bash
# Redis (jeśli używasz)
redis-cli info stats

# ZMQ — brak natywnych metryk (wymaga custom logger)
```

## Alerty i thresholdy

⚠️ **Wymaga weryfikacji:** Czy skrypty implementują alerty?

Możliwe mechanizmy:
- Email alert (przez `mail` lub `sendmail`)
- Publish na topik `system.alert`
- Logowanie do pliku `/var/log/rider/alerts.log`
- Wywołanie webhook

### Przykład (jeśli zaimplementowane)

```bash
# Ustaw threshold
export CPU_ALERT_THRESHOLD=80  # %
export TEMP_ALERT_THRESHOLD=70 # °C
./ops/monitor_metrics.sh
```

---

## Eksport metryk

### Grafana / Prometheus (integracja)

⚠️ **Wymaga weryfikacji:** Czy istnieje integracja?

Możliwe podejścia:
1. **Node Exporter:** Metryki systemowe
2. **Custom exporter:** Rider-Pi specific metrics
3. **StatsD/InfluxDB:** Time-series database

### Przykład setup (jeśli planowane)

```bash
# Install Node Exporter
# Setup Prometheus scraping
# Visualize in Grafana
```

---

## Zobacz także

- Systemd journal: `journalctl -u rider-*.service`
- System logs: `/var/log/syslog`, `/var/log/rider/`
- BUS debugging: `apps.bus` tools

**Related docs:**
- [docs/ops/systemd-scripts.md](systemd-scripts.md) — zarządzanie usługami

**Ostatnia aktualizacja:** 2025-01  
**Status:** ⚠️ Większość szczegółów wymaga weryfikacji kodu źródłowego
