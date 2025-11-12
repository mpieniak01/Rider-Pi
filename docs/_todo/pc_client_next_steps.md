# Rider-PI PC Client — Następne kroki wdrożeniowe

## 1. Skonfiguruj bezpieczny kanał sieciowy między Rider-PI a WSL
- Wybierz mechanizm: lekkie połączenie VPN (WireGuard) lub mTLS (np. Nginx jako reverse proxy).
- Przygotuj plan adresacji IP oraz zasady firewall na Windows i w Debian WSL (iptables/ufw) umożliwiające tylko wymagane porty (`8080`, `5555-5556`, ewentualne porty kolejki).
- Zarządzaj kluczami/certyfikatami przez centralny magazyn (np. Azure Key Vault, HashiCorp Vault) i wdróż procedurę rotacji.
- Zautomatyzuj uruchamianie tunelu przy starcie systemu (skrypt PowerShell + jednostka systemd w WSL).

## 2. Zaimplementuj adaptery REST/ZMQ i testy kontraktowe
- Zaimportuj istniejące schematy API Rider-PI (OpenAPI/JSON Schema) i wygeneruj klienta REST (np. `httpx` w asyncio).
- Utwórz moduł subskrypcji PUB/SUB ZMQ z mapowaniem tematów na lokalne eventy domenowe.
- Napisz testy kontraktowe porównujące odpowiedzi Rider-PI z oczekiwanymi schematami (pytest + `schemathesis` lub wbudowane asercje JSON).
- Dodaj testy integracyjne symulujące scenariusze UI (pobranie ekranów, potwierdzenie komend sterujących).

## 3. Przygotuj moduły PROVIDER (voice/vision/text) z kolejką zadań
- Zdefiniuj jednolite API zadaniowe (np. JSON Envelope `task_type`, `payload`, `meta`) wykorzystywane przez Rider-PI i providery.
- Uruchom broker zadań (RabbitMQ/Redis) w WSL; skonfiguruj Celery/Arq do obsługi kolejek priorytetowych.
- Dla każdego providera przygotuj konteneryzowane moduły inference z autotestami wydajności (benchmark CPU/GPU, metryki latency).
- Zaimplementuj fallback do lokalnych modeli Rider-PI, jeśli kolejka nieosiągalna.
- Zadbaj o telemetrię (czas przetwarzania, statusy) publikowaną z powrotem na bus ZMQ.

## 4. Zapewnij monitoring i logowanie
- Zainstaluj i skonfiguruj Prometheus Node Exporter oraz eksportery aplikacyjne (metrics endpoint FastAPI/Celery).
- Przygotuj dashboardy Grafana obejmujące: stan kolejki, latency API, wykorzystanie CPU/GPU, zużycie pamięci.
- Wprowadź standaryzację logów z prefiksami `[api]`, `[bridge]`, `[vision]`, `[voice]`, `[provider]`; skonfiguruj rotację (`logrotate`).
- Zintegruj alerty (Grafana/Alertmanager) dla krytycznych zdarzeń: brak połączenia z Rider-PI, przekroczenie SLA inference, brak miejsca na dysku.
- Uzgodnij politykę przechowywania logów i danych telemetrycznych (np. 30 dni lokalnie, archiwizacja w chmurze).

## 5. Dodatkowe działania operacyjne
- Przygotuj pipeline CI/CD uruchamiany z Windows (GitHub Actions/Self-Hosted runner) budujący obrazy i testujący adaptery.
- Opracuj procedury DR (Disaster Recovery): backup konfiguracji VPN, kluczy, kolejek oraz danych bufora.
- Przeszkol zespół w zakresie utrzymania środowiska WSL i diagnostyki (skrypty zdrowia, runbook awarii).