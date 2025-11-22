# Integracja z providerem PC / Offload

Jedyna aktualna referencja kontraktu pomiędzy urządzeniem Rider-Pi a towarzyszącym stosem Rider-PC.  
Dokument uzupełnia zewnętrzne notatki projektowe w repozytorium Rider-PC (zob.
[`Rider-Pc/docs/RIDER_PI_ARCH.md`](https://github.com/mpieniak01/Rider-Pc/blob/main/docs/RIDER_PI_ARCH.md) oraz
[`Rider-Pc/docs/ARCHITECTURE.md`](https://github.com/mpieniak01/Rider-Pc/blob/main/docs/ARCHITECTURE.md)).

## 1. Cele

1. Umożliwić operatorowi przełączanie obciążeń AI (Vision / Voice / Text) pomiędzy przetwarzaniem lokalnym a providerami PC bez restartów usług.
2. Odciążyć Rider-Pi – w trybie `pc` urządzenie ma jedynie zbierać dane z sensorów, przesyłać je do Rider-PC i odtwarzać wzbogacone wyniki.
3. Zachować kompatybilność z istniejącymi API REST i tematami ZMQ. Nowe możliwości providerów muszą być wyłącznie rozszerzeniem.
4. Zapewnić deterministyczny handshake, model zdrowia oraz zasady failbacku, gdy Rider-PC jest niedostępny.

## 2. Komponenty i odpowiedzialności

| Komponent | Lokalizacja | Zakres |
| --- | --- | --- |
| **Provider Registry** (`services/provider_registry.py`) | Rider-Pi | Przechowuje wybór providera per domena, udostępnia REST (`/api/providers/*`), publikuje zdarzenia (`provider.*.state`), monitoruje heartbeat i inicjuje powrót do `local` po serii błędów. |
| **Adaptery domenowe** (`apps/vision`, `apps/voice`, `apps/chat`) | Rider-Pi | Odczytują wybór providera i odpowiednio uruchamiają lokalne pipeline’y albo strumieniują dane do Rider-PC. Inne moduły (navigator, UI) korzystają z tych samych tematów co dotychczas. |
| **Stos Rider-PC** (`Rider-Pc/pc_client`) | PC | Konsumuje REST/ZMQ, uruchamia modele ML (Whisper, YOLOv8, Ollama...), publikuje wyniki z powrotem do Rider-Pi oraz eksponuje `/providers/*` dla negocjacji możliwości. |
| **UI sterujące** (`web/control.html`) | Rider-Pi | Prezentuje kartę Provider Control z przełącznikami na domenę, pokazuje stan połączenia i wywołuje `/api/providers/*`. |

## 3. Kontrakt REST (Rider-Pi)

| Endpoint | Metoda | Payload / Odpowiedź | Uwagi |
| --- | --- | --- | --- |
| `/api/providers/state` | `GET` | ```json\n{\n  \"domains\": {\n    \"vision\": {\"mode\": \"local\", \"status\": \"online\", \"changed_ts\": 1713360000.0},\n    \"voice\":  {...},\n    \"text\":   {...}\n  },\n  \"pc_health\": {\"reachable\": true, \"latency_ms\": 32}\n}\n``` | Dane do renderowania przełączników w UI. |
| `/api/providers/{domain}` | `PATCH` | `{"target": "local"|"pc", "force": false}` | Domena ∈ {`vision`, `voice`, `text`}. Przy przejściu na `pc` rejestr weryfikuje możliwości Rider-PC i publikuje `provider.{domain}.state`. |
| `/api/providers/health` | `GET` | Tabela heartbeat’ów z RTT, ostatnim sukcesem i licznikami błędów. | Źródło dla monitoringu. |
| `/api/system/ai-mode` | `PUT/GET` | Istniejący endpoint AI Mode. | Pozostaje niskopoziomowym przełącznikiem wykorzystywanym przez legacy; rejestr steruje nim automatycznie. |

### Negocjacja możliwości (Pi → PC)

1. Rejestr wywołuje `GET http://pc-host:8000/providers/capabilities`.
2. Rider-PC zwraca obsługiwane domeny i wersje schematów:
   ```json
   {
     "vision": {"version": "1.1.0", "features": ["obstacle", "depth"]},
     "voice":  {"version": "1.0.0", "features": ["asr", "tts"]},
     "text":   {"version": "1.0.0", "features": ["llm"]}
   }
   ```
3. Jeśli Rider-Pi wymaga nowszego schematu, rejestr pozostawia domenę w `local` i oznacza ją jako `blocked`.

## 4. Tematy ZMQ

| Kierunek | Topic | Payload | Opis |
| --- | --- | --- | --- |
| Pi → PC | `vision.frame.offload` | `{ "rid": "camera0", "ts": 123.4, "frame_jpeg": "<base64>", "roi": {...} }` | Strumień klatek/ROI w trybie `vision=pc`. |
| Pi → PC | `voice.asr.request` | `{ "rid": "voice", "ts": 123.4, "chunk_pcm": "<base64>", "lang": "pl-PL" }` | Fragmenty audio; odpowiedź trafia na `voice.asr.result`. |
| Pi → PC | `voice.tts.request` | `{ "text": "...", "voice": "piper-pl" }` | Opcjonalne – PC renderuje mowę. |
| PC → Pi | `vision.obstacle.enhanced` | `{ "present": true, "distance": 0.7, "angle": -12.0, "confidence": 0.91, "ts": 123.5 }` | Dane używane przez navigatora zamiast lokalnego ROI. |
| PC → Pi | `voice.asr.result` | `{ "text": "...", "intent": {...}, "reply": "...", "tts": {...}, "ts": 123.5 }` | Zwraca transkrypcję wraz z opcjonalnym intencją/komendą, tekstem odpowiedzi oraz danymi TTS (base64). |
| PC → Pi | `voice.tts.chunk` | Strumień PCM renderowany na Rider-PC (opcjonalnie). |
| PC → Pi | `provider.{domain}.heartbeat` | Krótkie ping’i zdrowia wykorzystywane przez rejestr (alternatywa dla HTTP). |

Wszystkie tematy działają na istniejącym brokerze (`services/broker.py`, porty 5555/5556). Payloady pozostają JSON UTF-8, kompatybilne wstecz.

## 5. Przepływy danych

### Zmiana trybu
1. Operator używa przełącznika w karcie Provider Control (`web/control.html`).
2. UI wywołuje `PATCH /api/providers/{domain}`.
3. Rejestr sprawdza możliwości Rider-PC i bieżący heartbeat.
4. Rejestr aktualizuje stan, zapisuje go, publikuje `provider.{domain}.state` i w razie potrzeby dostosowuje `RIDER_AI_MODE`.
5. Adapter domenowy otrzymuje zdarzenie i wznawia lokalne przetwarzanie albo zaczyna strumieniowanie do Rider-PC.

### Vision Offload
1. `apps/vision` korzysta z `VisionDispatcher`, aby wysyłać klatki na `vision.frame.offload`.
2. Rider-PC uruchamia YOLO/depth i publikuje `vision.obstacle.enhanced`.
3. Navigator subskrybuje temat i używa danych do planowania ruchu.

### Voice Offload
1. `apps/voice` pakuje PCM w `voice.asr.request` i oczekuje na `voice.asr.result`.
2. Po otrzymaniu tekstu istniejące pipeline’y (NLU, chat, sterowanie) działają bez zmian. Jeśli PC zwróci obiekt `intent`, Rider-Pi wykorzystuje go bez ponownego uruchamiania lokalnego NLU.
3. W przypadku TTS Rider-PC może zwrócić audio inline w polu `tts` (np. `{"format":"wav","sample_rate":16000,"data":"<b64>"}`) albo publikować `voice.tts.chunk`, które odtwarzamy lokalnie.
4. Rider-Pi oczekuje regularnych `voice.asr.result` nawet przy braku mowy użytkownika (np. `{"text": "", "status": "idle"}` co kilka sekund). Brak odpowiedzi powoduje automatyczny fallback do trybu lokalnego.

### Text / LLM Offload
1. Usługa chat sprawdza rejestr. W trybie `pc` wywołuje `http://pc-host:8000/providers/text/generate`.
2. Odpowiedzi trafiają do buźki / głosu identycznie jak w trybie lokalnym.

## 6. Obsługa awarii

- **Heartbeat**: Rejestr odpytuje Rider-PC co `PROVIDER_HEALTH_INTERVAL` sekund. Po przekroczeniu progu następuje automatyczny powrót do `local`.
- **Circuit breaker**: Każda domena liczy kolejne błędy. Domyślnie 3 błędne inferencje lub timeout >2 s przełączają na lokalne przetwarzanie.
- **Łagodne degradowanie**: Gdy PC jest offline, rejestr publikuje `provider.{domain}.state` ze statusem `fallback`, aby UI wyświetliło ostrzeżenie.
- **Manual override**: Operator może wymusić `local` nawet przy zdrowym PC. Parametr `force` omija różnicę wersji (z rozwagą).

## 7. Roadmapa wdrożenia

1. **Faza 1 – Rejestr i dokumentacja**  
   Implementacja `provider_registry.py`, REST, persystencja (`data/providers_state.json`), karta Provider Control w UI (na początku tryb tylko do odczytu).
2. **Faza 2 – MVP wizji**  
   `VisionDispatcher`, publikacja klatek, konsumpcja `vision.obstacle.enhanced` z mocka Rider-PC, weryfikacja navigatora/mapper’a.
3. **Faza 3 – Voice/Text**  
   Strumień audio, integracja z Whisper/Piper po stronie PC, endpointy `/providers/text/*`.
4. **Faza 4 – Monitoring/Ops**  
   Metryki (`/api/app-metrics`, grupa `provider`), dashboardy Grafana, jednostki systemd dla bridge’a providera.

## 8. Testy

- Testy kontraktowe w pytest z fikcyjnymi endpointami ZMQ (zgodność JSON ze schematami Rider-PC).
- Test UI (np. Cypress) walidujący przełączniki i reakcję na fallback.
- Test integracyjny navigatora – automatyczne przełączenie na `vision.obstacle.enhanced`.
- Testy obciążeniowe strumieni klatek (5 FPS, 640×480) pod kątem CPU i przepustowości.
- Testy awaryjne: zerwanie połączenia z Rider-PC → powrót do lokalnego trybu ≤2 s.

## 9. Dokumenty powiązane

- [`ui/control.md`](ui/control.md) — opisuje kartę Provider Control w interfejsie WWW.
- [`../docs/AI_MODE_SWITCHER.md`](../docs/AI_MODE_SWITCHER.md) — opis legacy AI mode switcher; rejestr providerów korzysta z niego do routingu per domena.
- [`archive/_todo/rider_pi_device_architecture.md`](archive/_todo/rider_pi_device_architecture.md) — stary szkic; bieżący dokument go zastępuje.
