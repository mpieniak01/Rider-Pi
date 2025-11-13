# Rider-PI Device — Architektura zmian pod integrację z providerem PC

## 1. Cel i zakres
- Zapewnienie dynamicznego wyboru źródła usług AI (lokalne modele na Rider-PI vs. providery PC).
- Rozszerzenie UI oraz API tak, aby operator mógł przełączać kanały obsługi głosu, tekstu i obrazu w locie.
- Utrzymanie kompatybilności wstecznej: brak zmian w dotychczasowych kontraktach bez zadeklarowanej negocjacji wersji.

## 2. Warstwa interfejsu web (web/)
- Dodanie panelu **Provider Control** dostępnego z menu ustawień, prezentującego sekcje: `Voice`, `Text`, `Vision`.
- Dla każdej sekcji udostępnione przełączniki (toggle) `Local` / `PC`, wraz ze wskaźnikiem stanu (`online`, `degraded`, `offline`).
- UI korzysta z istniejącego systemu komponentów (React/Vue) i komunikuje się z backendem przez nowe endpointy REST (patrz §3).
- Aktualny stan przełączników jest odpytywany periodycznie (`/api/providers/state`) oraz aktualizowany natychmiast po akcji (`PATCH /api/providers/{domain}`).
- Obsłuż fallback wizualny: jeśli provider PC niedostępny, UI automatycznie przełącza widok na `Local` i wyświetla ostrzeżenie.

## 3. Warstwa API i usług (services/)
### 3.1 Nowe endpointy REST
- `GET /api/providers/state` — zwraca listę domen (`voice`, `text`, `vision`) wraz z aktywnym źródłem (`local|pc`), stanem zdrowia oraz wersją kontraktu.
- `PATCH /api/providers/{domain}` — przyjmuje payload `{"target": "local|pc"}` i uruchamia proces przełączenia; endpoint wymaga autoryzacji operatora.
- `GET /api/providers/health` — zagnieżdżony raport dla monitoringu (łączność z PC, latency ostatnich zadań, błędy).

### 3.2 Orkiestrator providerów
- Nowa usługa `services/provider_registry.py` odpowiedzialna za przechowywanie stanu wyboru oraz handshake z providerami PC.
- Rejestr wykorzystuje pamięć współdzieloną (np. `common/state.py`) i publikuje zdarzenia na busie ZMQ (`provider.voice.state`, `provider.vision.state`).
- Orkiestrator wystawia API wewnętrzne do modułów domenowych (`apps/voice`, `apps/vision`, `apps/chat`) pozwalające pobrać aktualną destynację przetwarzania.
- Zapewnia mechanizm circuit breaker: po N błędach z rzędu przełącza się na `local` i emituje alert do UI/logów.

## 4. Zmiany w aplikacjach domenowych
### 4.1 Voice (`apps/voice`)
- Pipeline ASR/TTS rozszerzony o warstwę `ProviderGateway` realizującą wybór ścieżki:
  - `local`: dotychczasowe modele (por. `voice_local_file.toml`).
  - `pc`: wysłanie żądania do kolejki/busa PC (np. `voice.asr.request`) oraz oczekiwanie na odpowiedź (`voice.asr.result`).
- Obsługa time-outów i retry; wyniki zapisywane w tym samym formacie jak lokalne.

### 4.2 Text/Chat (`apps/chat`)
- Integracja z `provider_registry` przy generowaniu odpowiedzi LLM.
- W trybie `pc` moduł deleguje zapytania do API PC (`/providers/text/generate`), jednocześnie zapewniając caching i fallback do lokalnego pipeline.

### 4.3 Vision (`apps/vision`)
- Strumień obrazów z kamer kierowany przez nową warstwę `VisionDispatcher`:
  - `local`: obecne filtry/detekcje (`vision.toml`).
  - `pc`: pakietowanie klatek, wysłanie do PC (`vision.frame.offload`), odbiór wyników (maski, bounding boxy) i publikacja na busie (`vision.obstacle.enhanced`).
- Zaimplementuj kolejkę priorytetów, aby kluczowe zadania (np. obstacle avoidance) miały gwarantowaną obsługę lokalną w razie spadku jakości połączenia.

## 5. Przepływy danych i synchronizacja
- **Zmiana ustawień**: Operator w UI → `PATCH /api/providers/{domain}` → `provider_registry` zapisuje wybór → publikacja zdarzenia → moduły domenowe przełączają destynację.
- **Obsługa zadań głosowych**: Rider-PI nagrywa audio → `ProviderGateway` decyduje ścieżkę → (lokalne modele / wysyłka do PC) → wynik trafia do UI/twarzy.
- **Przetwarzanie wizji**: Kamera → `VisionDispatcher` → (lokalne przetwarzanie / offload) → publikacja wyników → mapowanie/nawigacja.
- **Telemetria stanu**: `provider_registry` agreguje heartbeat z PC (`/providers/heartbeat`, ZMQ) i udostępnia UI/monitoringowi.

## 6. Konfiguracja i negocjacja kontraktów
- Dodaj sekcję `providers` w plikach TOML (`config/voice.toml`, `config/vision.toml`) definiującą domyślny wybór oraz parametry konektora PC (adresy, time-outy, wersje API).
- Wprowadź mechanizm handshake (REST `GET /providers/capabilities`) ustalający wspierane domeny i wersje schematów JSON.
- Stosuj wersjonowanie semantyczne: `provider_registry` odrzuca połączenia z niekompatybilną wersją PC.

## 7. Bezpieczeństwo i niezawodność
- Endpointy przełączników wymagają silnego uwierzytelnienia (token operatora) oraz audytu (logi `[provider] switch domain=voice target=pc`).
- Kanały komunikacji z PC zabezpieczone mTLS/VPN; klucze rotowane zgodnie z polityką bezpieczeństwa.
- Mechanizm watchdog monitoruje RTT z PC; przekroczenie progu wyzwala alarm i automatyczny failback do `local`.

## 8. Wymagane aktualizacje dokumentacji i testów
- Zaktualizuj `ARCHITECTURE.md` oraz dokumentację API (`docs/api/`) o nowe endpointy i przepływy.
- Przygotuj testy integracyjne:
  - symulacja przełączenia providerów (pytest + fixtures ZMQ).
  - scenariusze degradacji (brak odpowiedzi PC, opóźnienia, błędy kontraktu).
- Dodaj checklistę w runbooku operacyjnym dotyczącą monitorowania providerów i ręcznego przełączania.