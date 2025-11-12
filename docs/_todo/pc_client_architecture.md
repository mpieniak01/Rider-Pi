# Rider-PI PC Client — Architektura rozwiązania

## 1. Warstwa systemowa (Windows 11 + WSL2 Debian)
- Windows uruchamia maszynę WSL2 z dystrybucją Debian, w której utrzymywany jest kod kliencki w Pythonie 3.9.
- Sieć WSL umożliwia bezpośrednią komunikację IP (LAN/VPN) pomiędzy Rider-PI a PC.
- Zasoby obliczeniowe PC (CPU/GPU) są udostępniane do WSL; w razie potrzeby włącz obsługę GPU (`wsl --install --webgpu`).

## 2. Warstwa aplikacji w WSL (Python 3.9)
### 2.1 Adapter API Rider-PI
- Moduł konsumujący REST (`/healthz`, `/api/control`, `/api/chat/*`) oraz strumienie ZMQ (porty 5555/5556).
- Zapewnia zgodność kontraktową z usługami Rider-PI oraz mapuje tematy busa na lokalne zdarzenia.

### 2.2 Replikator UI Web
- Serwer (np. FastAPI + komponent frontendowy) renderujący widoki 1:1 z oryginalnym Rider-PI Web.
- Dane pochodzą z API Rider-PI i lokalnego bufora; UI wystawiany jest w sieci lokalnej PC.

### 2.3 Bufor/Cache danych
- Lekka baza (Redis/SQLite) przechowująca bieżące stany ekranów, zrzuty (`data/`, `snapshots/`) i surowe strumienie danych.
- Umożliwia szybkie odtworzenie UI oraz buforowanie pakietów dla providerów AI.

### 2.4 Warstwa PROVIDER (Voice/Text/Vision)
- Zestaw modułów inference wykorzystujących moc obliczeniową PC.
- Voice Provider: offload ASR/TTS z pipeline'u `apps/voice` (REST/ZMQ).
- Text Provider: dodatkowe modele NLU/NLG (lokalne lub chmurowe, z lokalnym proxy bezpieczeństwa).
- Vision Provider: przetwarzanie obrazów/strumieni (`apps/vision`) z możliwością rozbudowy (np. depth estimation).

### 2.5 Kolejka zadań
- Broker (RabbitMQ/Redis) i warstwa Celery/Arq do asynchronicznego offloadu zadań.
- Zapewnia buforowanie oraz równoważenie obciążenia pomiędzy providerami.

## 3. Warstwa komunikacji i integracji
### 3.1 Kanały przychodzące z Rider-PI
- REST (port 8080) tunelowany przez VPN/mTLS.
- Strumień ZMQ PUB/SUB (5555/5556) z tematami `vision.*`, `voice.*`, `motion.state`, `robot.pose`.
- Transfer plików (SFTP/rsync/HTTP static) z katalogów `data/`, `snapshots/`.

### 3.2 Kanały wychodzące do Rider-PI
- REST (`/api/control`, `/api/chat/*`) dla komend i odpowiedzi rozszerzonych usług AI.
- PUB ZMQ z tematami typu `vision.obstacle.enhanced`, `voice.tts.chunk`, `events.sentiment.offload`.
- Zwracanie plików wynikowych (audio, mapy) kanałem SFTP/HTTP PUT.

## 4. Przepływy danych
- **Synchronizacja ekranów:** Rider-PI → REST/ZMQ → Bufor PC → Web UI → Przeglądarka użytkownika.
- **Offload głosu:** Rider-PI (audio chunk) → ZMQ/HTTP → Voice Provider → Wyniki ASR/TTS → Rider-PI UI/voice.
- **Offload wizji:** Rider-PI (`snapshots/`, `vision.person`) → Vision Provider → Dane wzbogacone → Rider-PI mapper/navigator.
- **Offload tekstu:** Rider-PI prompt → LLM PC → Odpowiedź → Rider-PI interfejs (web/twarz).

## 5. Rozszerzalność i zarządzanie
- Providerów implementuj jako pluginy (`providers/`), rejestrowane podczas startu.
- Wersjonuj kontrakty (schematy JSON) i negocjuj możliwości z Rider-PI.
- Zadbaj o telemetrię i logging spójny z prefiksami `[api]`, `[bridge]`, `[vision]`, `[voice]`, `[provider]`.

## 6. Instalacja środowiska (skrót)
- Instalacja WSL Debian: `wsl --install -d Debian`, następnie `wsl --update`.
- W WSL wykonaj: `sudo apt update && sudo apt upgrade -y`.
- Zainstaluj pakiety bazowe i ML: `sudo apt install -y build-essential python3.9 python3.9-venv python3.9-dev git curl wget unzip pkg-config cmake ninja-build libzmq3-dev libssl-dev libffi-dev libjpeg-dev zlib1g-dev libgl1 libglib2.0-0 libopenblas-dev libsndfile1 ffmpeg alsa-utils portaudio19-dev`.
- (Opcjonalnie) GPU: `sudo apt install -y nvidia-cuda-toolkit nvidia-cudnn`.
- Utwórz środowisko Python: `python3.9 -m venv ~/venvs/rider-pi-pc && source ~/venvs/rider-pi-pc/bin/activate && pip install --upgrade pip`.

## 7. Konfiguracja i dalsze prace
- Skonfiguruj bezpieczne kanały sieciowe, adaptery REST/ZMQ, kolejkę zadań oraz monitoring (Prometheus/Grafana).
- Przygotuj pipeline CI/CD dla budowy i testów oraz runbooki operacyjne.