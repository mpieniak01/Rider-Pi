# Integracja Google Home z Rider-Pi

## Przegląd

Rider-Pi obsługuje sterowanie urządzeniami smart home zintegrowanymi z Google Home poprzez Smart Device Management API. Ta funkcjonalność umożliwia:

- Zarządzanie urządzeniami Google Home z poziomu interfejsu webowego Rider-Pi
- Włączanie/wyłączanie urządzeń obsługujących cechę OnOff
- Regulację jasności urządzeń obsługujących cechę Brightness
- Bezpieczne przechowywanie tokenów autoryzacyjnych

## Architektura

### Backend

**Moduł: `services/api_core/google_home_api.py`**

Moduł odpowiedzialny za komunikację z Google Smart Device Management API:

- **OAuth 2.0 Flow**: Obsługa autoryzacji użytkownika przez Google
- **Token Management**: Przechowywanie i odświeżanie tokenów dostępu
- **Device Management**: Pobieranie listy urządzeń
- **Command Execution**: Wysyłanie komend do urządzeń

### API Endpoints

API Server (`services/api_server.py`) udostępnia następujące endpointy:

#### GET `/api/home/auth`
Inicjuje proces autoryzacji OAuth 2.0. Przekierowuje użytkownika do strony logowania Google.

**Odpowiedź**: HTTP 302 Redirect do Google OAuth

#### GET `/api/home/oauth2callback`
Endpoint obsługujący callback z Google po zakończeniu autoryzacji.

**Parametry URL**:
- `code` (string): Kod autoryzacyjny zwrócony przez Google

**Odpowiedź**: HTTP 302 Redirect do `/web/home.html?auth=success`

#### GET `/api/home/status`
Sprawdza status autoryzacji (czy użytkownik jest zalogowany).

**Odpowiedź**:
```json
{
  "ok": true,
  "authenticated": true
}
```

#### GET `/api/home/devices`
Pobiera listę urządzeń Google Home.

**Wymagania**: Użytkownik musi być zalogowany

**Odpowiedź**:
```json
{
  "ok": true,
  "devices": [
    {
      "name": "enterprises/project-id/devices/device-id",
      "type": "sdm.devices.types.LIGHT",
      "traits": {
        "sdm.devices.traits.OnOff": {
          "on": false
        },
        "sdm.devices.traits.Brightness": {
          "brightness": 50
        }
      }
    }
  ]
}
```

#### POST `/api/home/command`
Wysyła komendę do urządzenia.

**Wymagania**: Użytkownik musi być zalogowany

**Request Body**:
```json
{
  "deviceId": "enterprises/project-id/devices/device-id",
  "command": "action.devices.commands.OnOff",
  "params": {
    "on": true
  }
}
```

**Odpowiedź**:
```json
{
  "ok": true,
  "result": {}
}
```

**Przykładowe komendy**:

- Włącz/wyłącz urządzenie:
  ```json
  {
    "command": "action.devices.commands.OnOff",
    "params": {"on": true}
  }
  ```

- Ustaw jasność:
  ```json
  {
    "command": "action.devices.commands.BrightnessAbsolute",
    "params": {"brightness": 75}
  }
  ```

### Frontend

**Plik: `web/home.html`**

Interfejs webowy zapewnia:

- Przycisk logowania przez Google (gdy użytkownik nie jest zalogowany)
- Listę urządzeń z dynamicznie generowanymi kontrolkami
- Przyciski On/Off dla urządzeń obsługujących OnOff
- Suwaki jasności dla urządzeń obsługujących Brightness
- Komunikaty o statusie i błędach
- Obsługę wielu języków (polski/angielski) poprzez `i18n.js`

## Konfiguracja

### 1. Konfiguracja Google Cloud Console

1. Przejdź do [Google Cloud Console](https://console.cloud.google.com/)
2. Utwórz nowy projekt lub wybierz istniejący
3. Włącz **Smart Device Management API**:
   - Przejdź do "APIs & Services" → "Library"
   - Wyszukaj "Smart Device Management API"
   - Kliknij "Enable"

4. Utwórz dane uwierzytelniające OAuth 2.0:
   - Przejdź do "APIs & Services" → "Credentials"
   - Kliknij "Create Credentials" → "OAuth client ID"
   - Wybierz typ aplikacji: "Web application"
   - Dodaj Authorized redirect URI: `http://199.168.1.71:5000/api/home/oauth2callback`
     (zmień IP/port jeśli używasz innego adresu)
   - Zapisz **Client ID** i **Client Secret**

### 2. Konfiguracja Device Access Console

1. Przejdź do [Device Access Console](https://console.nest.google.com/device-access/)
2. Utwórz nowy projekt Device Access (wymagana opłata 5 USD)
3. Zapisz **Project ID** z utworzonego projektu

### 3. Konfiguracja zmiennych środowiskowych

1. Skopiuj przykładowy plik konfiguracji:
   ```bash
   cp .bash_profile_example ~/.bash_profile
   ```

2. Edytuj `~/.bash_profile` i uzupełnij zmienne:
   ```bash
   export GOOGLE_CLIENT_ID="twoj-client-id.apps.googleusercontent.com"
   export GOOGLE_CLIENT_SECRET="twoj-client-secret"
   export GOOGLE_PROJECT_ID="twoj-project-id"
   ```

3. Załaduj zmienne środowiskowe:
   ```bash
   source ~/.bash_profile
   ```

4. Opcjonalnie: Dodaj do `~/.bashrc` aby załadować przy każdym logowaniu:
   ```bash
   echo "source ~/.bash_profile" >> ~/.bashrc
   ```

### 4. Instalacja zależności

```bash
pip install -r requirements-dev.txt
```

Lub ręcznie:
```bash
pip install google-auth-oauthlib google-auth requests
```

### 5. Uruchomienie serwera

```bash
python services/api_server.py
```

Serwer domyślnie startuje na porcie 5000 (konfigurowalny przez zmienną `STATUS_API_PORT`).

## Użycie

### Proces autoryzacji

1. Otwórz w przeglądarce: `http://199.168.1.71:5000/web/home.html`
2. Kliknij przycisk "Zaloguj przez Google"
3. Zaloguj się kontem Google i udziel zgód dla aplikacji
4. Zostaniesz przekierowany z powrotem do panelu Rider-Pi
5. Po pomyślnej autoryzacji zobaczysz listę urządzeń

### Sterowanie urządzeniami

- **On/Off**: Kliknij przyciski "Włącz" lub "Wyłącz"
- **Jasność**: Przesuń suwak do żądanej wartości (zmiana jest wysyłana po zwolnieniu suwaka)
- **Odświeżanie**: Kliknij przycisk "⟳ Odśwież" aby zaktualizować listę i stany urządzeń

### Zarządzanie tokenami

- Tokeny są przechowywane w: `config/local/google_tokens.json`
- Plik jest automatycznie dodany do `.gitignore` (nie jest śledzony przez Git)
- Token dostępu (access token) jest automatycznie odświeżany gdy wygaśnie
- Token odświeżający (refresh token) jest zapisywany trwale
- Aby wylogować się, usuń plik `config/local/google_tokens.json`

## Bezpieczeństwo

### Przechowywanie sekretów

- **NIE** commituj pliku `.bash_profile` do repozytorium
- **NIE** commituj pliku `config/local/google_tokens.json` do repozytorium
- Zmienne środowiskowe są odczytywane z `~/.bash_profile` użytkownika
- Przykładowy plik `.bash_profile_example` zawiera tylko placeholdery

### Zabezpieczenia OAuth

- Wykorzystywany jest flow "offline access" dla długotrwałej autoryzacji
- Access token ma ograniczony czas życia (1 godzina)
- Refresh token pozwala na automatyczne odświeżanie bez ponownego logowania
- Scope API: `https://www.googleapis.com/auth/sdm.service`

### CORS

- Wszystkie endpointy `/api/home/*` obsługują CORS
- Dozwolone wszystkie originy (`Access-Control-Allow-Origin: *`)
- W środowisku produkcyjnym rozważ ograniczenie originów

## Rozwiązywanie problemów

### "GOOGLE_CLIENT_ID not set"

- Sprawdź czy zmienne środowiskowe są poprawnie ustawione:
  ```bash
  echo $GOOGLE_CLIENT_ID
  echo $GOOGLE_CLIENT_SECRET
  echo $GOOGLE_PROJECT_ID
  ```
- Upewnij się, że załadowałeś plik: `source ~/.bash_profile`
- Restart serwera API po ustawieniu zmiennych

### "Not authenticated or token refresh failed"

- Sprawdź czy plik `config/local/google_tokens.json` istnieje
- Jeśli plik istnieje ale błąd się powtarza, usuń go i zaloguj się ponownie
- Sprawdź logi serwera pod kątem błędów odświeżania tokena

### "No devices found"

- Sprawdź czy urządzenia są poprawnie skonfigurowane w Google Home
- Zweryfikuj Project ID w Device Access Console
- Upewnij się, że konto Google ma dostęp do urządzeń
- Sprawdź czy w Device Access Console projekt ma dostęp do urządzeń

### Błędy OAuth callback

- Sprawdź czy Redirect URI w Google Cloud Console jest identyczny z używanym
- Format: `http://IP:PORT/api/home/oauth2callback`
- Sprawdź czy serwer jest dostępny pod podanym adresem IP

### Błędy CORS w przeglądarce

- Upewnij się, że serwer API działa
- Sprawdź czy metody OPTIONS są poprawnie obsługiwane
- Sprawdź konsole przeglądarki pod kątem szczegółowych błędów

## Struktura plików

```
Rider-Pi/
├── .bash_profile_example          # Przykład konfiguracji zmiennych środowiskowych
├── .gitignore                      # google_tokens.json dodany
├── requirements-dev.txt            # Zależności (google-auth-oauthlib, etc.)
├── services/
│   ├── api_server.py              # Routing endpointów /api/home/*
│   └── api_core/
│       └── google_home_api.py     # Główny moduł Google Home API
├── web/
│   ├── home.html                  # Interfejs sterowania
│   └── i18n.js                    # Tłumaczenia (home.*)
├── config/
│   └── local/
│       └── google_tokens.json     # Przechowywane tokeny (nie w Git)
└── docs/
    └── google-home-integration.md # Ten dokument
```

## Zmiany w kodzie

### Nowe pliki
- `services/api_core/google_home_api.py` - główny moduł integracji
- `web/home.html` - interfejs webowy
- `.bash_profile_example` - przykładowa konfiguracja
- `docs/google-home-integration.md` - dokumentacja

### Zmodyfikowane pliki
- `services/api_server.py` - dodano routing `/api/home/*`
- `web/i18n.js` - dodano tłumaczenia `home.*`
- `web/view.html` - dodano link do panelu Google Home
- `.gitignore` - dodano `config/local/google_tokens.json`
- `requirements-dev.txt` - dodano zależności Google API

## API Reference

### Klasy i funkcje (google_home_api.py)

#### `get_auth_url() -> str`
Generuje URL autoryzacji OAuth 2.0.

**Zwraca**: URL do przekierowania użytkownika

**Wyjątki**: `ValueError` jeśli brakuje CLIENT_ID lub CLIENT_SECRET

#### `handle_oauth_callback(code: str) -> dict`
Obsługuje callback OAuth i wymienia kod na tokeny.

**Parametry**:
- `code`: Kod autoryzacyjny

**Zwraca**: `{"ok": True/False, "message": "...", "error": "..."}`

#### `is_authenticated() -> bool`
Sprawdza czy użytkownik jest zalogowany.

**Zwraca**: `True` jeśli refresh token istnieje

#### `refresh_access_token() -> str | None`
Odświeża access token używając refresh tokena.

**Zwraca**: Nowy access token lub `None` w przypadku błędu

#### `get_devices() -> dict`
Pobiera listę urządzeń z API.

**Zwraca**: 
```python
{
    "ok": True/False,
    "devices": [...],  # jeśli ok=True
    "error": "...",    # jeśli ok=False
    "status_code": 401 # opcjonalnie, przy błędzie auth
}
```

#### `send_command(device_id: str, command: str, params: dict) -> dict`
Wysyła komendę do urządzenia.

**Parametry**:
- `device_id`: Pełne ID urządzenia
- `command`: Nazwa komendy (np. "action.devices.commands.OnOff")
- `params`: Parametry komendy

**Zwraca**:
```python
{
    "ok": True/False,
    "result": {...},   # jeśli ok=True
    "error": "...",    # jeśli ok=False
    "status_code": 401 # opcjonalnie, przy błędzie auth
}
```

## Dalszy rozwój

Potencjalne rozszerzenia funkcjonalności:

- [x] Obsługa dodatkowych cech urządzeń (ColorSetting, TemperatureSetting, StartStop, Dock)
- [ ] Grupowanie urządzeń według pokoi
- [ ] Zaplanowane akcje (timer, harmonogram)
- [ ] Sceny i automatyzacje
- [ ] Integracja z systemem głosowym Rider-Pi
- [ ] Wsparcie dla wielu kont Google
- [ ] Panel administracyjny do zarządzania autoryzacjami
- [ ] WebSocket do real-time aktualizacji stanów urządzeń
- [ ] Tryb offline z cache'owaniem stanów
- [ ] Logi historyczne zmian stanów urządzeń

## Obsługiwane typy urządzeń i cechy

Rider-Pi obecnie obsługuje następujące cechy (traits) urządzeń Google Home:

### OnOff
Włączanie i wyłączanie urządzeń.

**Kontrolki UI:**
- Przyciski "Włącz" i "Wyłącz"
- Wyświetlanie aktualnego stanu (ON/OFF)

**Komenda API:**
```json
{
  "command": "action.devices.commands.OnOff",
  "params": {"on": true}
}
```

### Brightness
Regulacja jasności urządzeń oświetleniowych.

**Kontrolki UI:**
- Suwak od 0 do 100
- Wyświetlanie aktualnej wartości w procentach

**Komenda API:**
```json
{
  "command": "action.devices.commands.BrightnessAbsolute",
  "params": {"brightness": 75}
}
```

### ColorSetting
Ustawianie koloru i temperatury barwowej światła.

**Kontrolki UI:**
- Suwak temperatury barwowej (2000K - 6500K)
- Selektor koloru RGB (color picker)

**Komendy API:**
```json
// Temperatura barwowa
{
  "command": "action.devices.commands.ColorAbsolute",
  "params": {
    "color": {
      "temperatureK": 3000
    }
  }
}

// Kolor RGB
{
  "command": "action.devices.commands.ColorAbsolute",
  "params": {
    "color": {
      "spectrumRgb": 16711680
    }
  }
}
```

### TemperatureSetting
Sterowanie termostatami - ustawianie temperatury i trybu pracy.

**Kontrolki UI:**
- Przyciski +/- do zmiany temperatury zadanej
- Wyświetlanie temperatury otoczenia (jeśli dostępna)
- Lista rozwijana do wyboru trybu termostatu

**Komendy API:**
```json
// Ustawienie temperatury
{
  "command": "action.devices.commands.ThermostatTemperatureSetpoint",
  "params": {
    "thermostatTemperatureSetpoint": 22.5
  }
}

// Zmiana trybu
{
  "command": "action.devices.commands.ThermostatSetMode",
  "params": {
    "thermostatMode": "heat"
  }
}
```

**Dostępne tryby:**
- `off` - Wyłączony
- `heat` - Ogrzewanie
- `cool` - Chłodzenie
- `heatcool` - Automatyczny (ogrzewanie/chłodzenie)
- `eco` - Tryb ekonomiczny
- `on` - Włączony

### StartStop
Uruchamianie i zatrzymywanie urządzeń (np. odkurzaczy robotycznych).

**Kontrolki UI:**
- Przyciski "Start", "Stop", "Pauza"
- Wyświetlanie aktualnego stanu (RUNNING/PAUSED/STOPPED)

**Komendy API:**
```json
// Start
{
  "command": "action.devices.commands.StartStop",
  "params": {"start": true}
}

// Stop
{
  "command": "action.devices.commands.StartStop",
  "params": {"start": false}
}

// Pauza
{
  "command": "action.devices.commands.PauseUnpause",
  "params": {"pause": true}
}
```

### Dock
Wysyłanie urządzenia do bazy ładującej.

**Kontrolki UI:**
- Przycisk "Wróć do bazy"

**Komenda API:**
```json
{
  "command": "action.devices.commands.Dock",
  "params": {}
}
```

## Referencje

- [Smart Device Management API Documentation](https://developers.google.com/nest/device-access/api)
- [Google OAuth 2.0 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Device Access Console](https://console.nest.google.com/device-access/)
- [Google Cloud Console](https://console.cloud.google.com/)

## Licencja

Zgodnie z główną licencją projektu Rider-Pi.
