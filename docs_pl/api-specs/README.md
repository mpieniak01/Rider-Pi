# HTTP API Rider-Pi

[Jednolity kontrakt Pi/PC](contracts.md) opisuje negocjowane koperty v1.
Przykłady bez negocjacji dotyczą projekcji legacy. Wersja koperty, schemat danych,
rewizja nastaw i generacja poleceń są odrębnymi wartościami.

Główna usługa to rider-api.service, punkt wejścia
[services/api_server.py](../../services/api_server.py), port 8080.
[Granica HTTP](security.md) działa przed handlerami: przeglądarka korzysta
z własnego originu, dodatkowe wymagają RIDER_ALLOWED_ORIGINS. Zaufanie hosta
nie zastępuje uwierzytelniania. Obce originy są odrzucane także dla OPTIONS.
Niepuste mutacje wymagają JSON poza opisanymi wyjątkami uploadu binarnego.
Nie ma nieograniczonego CORS z wildcardem.

## Interfejsy

| Obszar | Endpointy lub przewodnik |
| --- | --- |
| Zdrowie i stan | GET /healthz, /api/status, /api/safety, /api/control/state, /api/status/version |
| Ruch i bezpieczeństwo | [Sterowanie](control.md), [zamiar ręczny i deskryptory](manual-motion.md), [własność panelu](../manual-panel-authority.md) |
| Kalibracja | GET/POST /api/calibration/controls; [nastawy i profile](../apps/calibration.md) |
| Lokalna nawigacja | /api/navigator/*; [navigator](navigator.md), osobny od pętli Venoma |
| Nawigacja Venoma | /api/navigation/config, /status, /trial, /journey; [kontrakt kierunkowy](../DIRECTIONAL_NAVIGATION.md), [podróż](../AUTOMAT2_JOURNEY_V1.md) |
| Profile i wybór modelu | /api/navigation/models, /local-models, /model, /model-selection; [modele](../apps/perception-models.md), [parametry polityki](../vision-policy-parameters.md) |
| Pomoc pomiarowa | GET/POST /api/navigation/image-reference; [osobna referencja obrazu](../IMAGE_REFERENCE.md) |
| Źródło kamery | /api/resource/camera/pipeline; [pipeline](../CAMERA_PIPELINE_V1.md), [wyłączenie źródła](../apps/camera-source-off.md) |
| Zdalne obliczenia | /api/compute/config, /status, /tasks/<task>; [parowanie Venoma](../COMPUTE_VENOM.md), [kontrakt providera](../OFFLOAD_PROVIDER_PROTOCOL.md) |
| Impuls agenta i gotowy dźwięk | /api/control/agent/state, /pulse, /api/voice/playback, /cancel; [kontrakt prywatnego Bearer](../apps/agent-control.md) |
| Zadania i zasoby operatora | [Sterowanie operatora](../OPERATOR_CONTROL_V1.md), [zasoby](../ARCHITEKTURA_ZASOBOW.md) |

Wiersze ze wspólnym prefiksem skracają pełne nazwy tras; nie tworzą nowych
endpointów w korzeniu. Odczyt GET nie przyznaje uprawnienia ruchu.
POST trial/journey to jawne działania, a nie pasywny odczyt.
Rejestracja tras jest rozdzielona między moduły api_core. Dostępność zależy
od ogłoszonych funkcji i aktualnego stanu wykonawcy.

## Metryki aplikacji

GET /api/app-metrics zwraca liczniki interaktywnych endpointów: metrics według
control, navigator, voice, google_home, chat i face oraz total_errors.
Każda grupa ma ok/error. Liczniki nie potwierdzają wykonania fizycznego,
gotowości ani bezpieczeństwa i nie zastępują świeżego stanu wykonawcy.

## Odpowiedzi i czas

Nowe klienty używają negocjowanego kontraktu. Starsze kształty JSON zależą
od endpointu; nie zakładaj jednej uniwersalnej struktury {ok,data}.
Potwierdzenie operacji odróżnia zapis konfiguracji, działanie zadania i przyjęcie
przez SDK. ACK SDK nie potwierdza fizycznego wykonania.

server_time pomaga uzgodnić czas polecenia. observed_at i czas capture opisują
rzeczywisty pomiar; odbiór HTTP nie zastępuje tych wartości.
Czas monotoniczny należy do domeny zegara danego procesu/hosta.

## Media, pliki i BUS

API serwuje [strony operatora](../ui/README.md). Zarządzane klatki i strumienie
zachowują tożsamość źródła i świeżość; statyczny JPEG nie potwierdza żywego
producenta. Pliki są ograniczone do skonfigurowanych katalogów.
[Ograniczenia HTTP i plików](security.md).

Handlery mogą publikować na ZMQ przez [common/bus.py](../../common/bus.py).
Sama publikacja nie jest terminalnym ACK. [Wykonanie ruchu](../apps/motion.md)
pozostaje na Pi; wykonawca sprawdza generację, sekwencję, TTL, owner i rewizję.
