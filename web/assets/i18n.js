// web/i18n.js
export const I18N = {
  meta: {
    app_title: { pl: "Rider-Pi — Sterowanie ruchem (REST /api)", en: "Rider-Pi — Motion Control (REST /api)" },
    loading:   { pl: "Ładowanie…", en: "Loading…" },
    ok:        { pl: "OK", en: "OK" },
    warn:      { pl: "Ostrzeżenie", en: "Warning" },
    error:     { pl: "Błąd", en: "Error" },
    dashboard: { pl: "↩ pulpit", en: "↩ dashboard" },
  },

  header: {
    api_status_checking: { pl: "(sprawdzanie…)", en: "(checking…)" },
    api_status_ok:       { pl: "ok", en: "ok" },
    api_status_degraded: { pl: "ograniczone", en: "degraded" },
    api_status_down:     { pl: "niedostępne", en: "down" },

    obstacle_na:      { pl: "Przeszkoda: n/d", en: "Obstacle: n/a" },
    obstacle_present: { pl: "Przeszkoda: WYKRYTA", en: "Obstacle: DETECTED" },
    obstacle_none:    { pl: "Przeszkoda: brak", en: "Obstacle: none" },
  },

  nav: {
    brand_title:   { pl: "Rider-Pi", en: "Rider-Pi" },
    brand_sub:     { pl: "Panel operatora", en: "Operator console" },
    view:          { pl: "Przegląd", en: "Overview" },
    control:       { pl: "Sterowanie", en: "Control" },
    navigation:    { pl: "Nawigacja", en: "Navigation" },
    system:        { pl: "System", en: "System" },
    home:          { pl: "Statusy", en: "Status" },
    google_home:   { pl: "Google Home", en: "Google Home" },
    chat:          { pl: "Chat", en: "Chat" },
    lang_pl_title: { pl: "Przełącz na polski", en: "Switch to Polish" },
    lang_en_title: { pl: "Przełącz na angielski", en: "Switch to English" },
  },

  // ===== MINI DASHBOARD =====
  dash: {
    page_title:     { pl: "Rider-Pi — mini dashboard", en: "Rider-Pi — mini dashboard" },
    hint_prefix:    { pl: "Auto-refresh co ≈ 2 s.",   en: "Auto-refresh every ≈ 2 s." },
    hint_endpoints: { pl: "Endpointy:",                en: "Endpoints:" },

    system: {
      title:  { pl: "System", en: "System" },
      cpu_est:{ pl: "cpu (szac.)", en: "cpu (est)" },
      load:   { pl: "load (1/5/15)", en: "load (1/5/15)" },
      mem:    { pl: "pamięć", en: "mem" },
      disk:   { pl: "dysk",   en: "disk" },
      os:     { pl: "os",     en: "os" },
      fw:     { pl: "fw",     en: "fw" },
    },

    devices: {
      title:      { pl: "Urządzenia", en: "Devices" },
      camera:     { pl: "kamera",     en: "camera" },
      lcd:        { pl: "lcd",        en: "lcd" },
      xgo_imu:    { pl: "xgo.imu",    en: "xgo.imu" },
      xgo_pose:   { pl: "xgo.pozycja",en: "xgo.pose" },
      xgo_battery:{ pl: "xgo.bateria",en: "xgo.battery" },
      temp:       { pl: "temp",       en: "temp" },
    },

    history: {
      title: { pl: "Historia (60 s) — CPU / MEM", en: "History (60 s) — CPU / MEM" },
      cpu:   { pl: "cpu%", en: "cpu%" },
      mem:   { pl: "mem%", en: "mem%" },
    },

    camera: {
      title:          { pl: "Kamera",                en: "Camera" },
      caption:        { pl: "podgląd (ostatnia klatka lub komunikat)", en: "preview (last frame or message)" },
      vision_on:      { pl: "vision: ON",            en: "vision: ON" },
      vision_off:     { pl: "vision: OFF",           en: "vision: OFF" },
      resource_free_badge: { pl: "kamera: wolna", en: "camera: free" },
      resource_busy_badge: { pl: "kamera: zajęta", en: "camera: busy" },
      resource_busy_with_holder: { pl: "kamera: zajęta ({holder})", en: "camera: busy ({holder})" },
      resource_error_badge: { pl: "kamera: błąd zasobu", en: "camera: resource error" },
      last_frame_ts:  { pl: "ostatnia klatka:",      en: "last frame:" },
      no_last_frame:  { pl: "brak ostatniej klatki", en: "no last frame" },
    },

    health: {
      title:                  { pl: "Kondycja", en: "Health" },
      status:                 { pl: "status", en: "status" },
      uptime:                 { pl: "czas działania",         en: "uptime" },
      bus_last_msg_age:       { pl: "bus: wiek ostatniej wiadomości",  en: "bus.last_msg_age" },
      bus_last_heartbeat_age: { pl: "bus: wiek ostatniego heartbeat",  en: "bus.last_heartbeat_age" },
    },

    presence: {
      title:      { pl: "Obecność (vision.state)", en: "Presence (vision.state)" },
      present:    { pl: "obecny",    en: "present" },
      confidence: { pl: "pewność",   en: "confidence" },
      mode:       { pl: "tryb",      en: "mode" },
      ts:         { pl: "ts",        en: "ts" },
      age:        { pl: "wiek",      en: "age" },
    },

    links: {
      title:   { pl: "Linki",         en: "Links" },
      events:  { pl: "zdarzenia (SSE)", en: "events (SSE)" },
      metrics: { pl: "metryki",       en: "metrics" },
      repo:    { pl: "repozytorium",  en: "repo" },
      control: { pl: "sterowanie",    en: "control" },
      // zmiana etykiety na małe z kropką:
      home:    { pl: "google.home",   en: "google.home" },
    },

    camera_proc: {
      title:   { pl: "Kamera — PROC", en: "Camera — PROC" },
      caption: { pl: "ramki / etykiety", en: "boxes / labels" },
    },

    tracker: {
      legend:      { pl: "TRACKER", en: "TRACKER" },
      offset:      { pl: "offset", en: "offset" },
      offset_none: { pl: "offset: brak danych", en: "offset: n/a" },
      mode:        { pl: "tryb", en: "mode" },
      age:         { pl: "wiek", en: "age" },
    },

    // DODANE: sekcja repo używana przez kafel "Repozytorium"
    repo: {
      title:  { pl: "Repozytorium", en: "Repository" },
      name:   { pl: "projekt",      en: "project" },
      github: { pl: "GitHub",       en: "GitHub" },
    },

    status: {
      vision_prefix: { pl: "VISION:", en: "VISION:" },
      present:       { pl: "PRESENT", en: "PRESENT" },
      idle:          { pl: "IDLE",    en: "IDLE" },
      mode:          { pl: "mode",    en: "mode" },
      conf:          { pl: "conf",    en: "conf" },
      cam_prefix:    { pl: "CAM:",    en: "CAM:" }
    }
  },

  // ===== CONTROL PAGE =====
  camera: {
    title:             { pl: "Podgląd kamery", en: "Camera preview" },
    auto_refresh_on:   { pl: "⟳ Auto-odświeżanie (wł)", en: "⟳ Auto-refresh (on)" },
    auto_refresh_off:  { pl: "⟳ Auto-odświeżanie (wył)", en: "⟳ Auto-refresh (off)" },
    use_edge:          { pl: "Użyj EDGE", en: "Use EDGE" },
    use_cam:           { pl: "Użyj CAM",  en: "Use CAM" },
    last_frame:        { pl: "ostatnia klatka: {age} · źródło: {src}", en: "last frame: {age} · source: {src}" },
    last_frame_na:     { pl: "last frame: n/d · źródło: n/d", en: "last frame: n/a · source: n/a" },
    src_edge:          { pl: "EDGE",   en: "EDGE" },
    src_cam:           { pl: "CAM",    en: "CAM" },
    src_vision:        { pl: "VISION", en: "VISION" },
    src_none:          { pl: "brak",   en: "none" },
  },

  motion: {
    title:           { pl: "Sterowanie ruchem", en: "Motion control" },
    turning_speed:   { pl: "Prędkość skrętu",   en: "Turning speed" },
    turning_range:   { pl: "(0..1)",            en: "(0..1)" },
    max_speed:       { pl: "Prędkość maksymalna", en: "Max speed" },
    max_speed_range: { pl: "(0..1)",            en: "(0..1)" },
    pulse_time:      { pl: "Czas impulsu [s]",  en: "Pulse time [s]" },
    btn_stop:        { pl: "■ STOP",            en: "■ STOP" },
    btn_stop_small:  { pl: "■ Stop",            en: "■ Stop" },
    btn_forward:     { pl: "↑ Naprzód",         en: "↑ Forward" },
    btn_backward:    { pl: "↓ Wstecz",          en: "↓ Backward" },
    btn_left:        { pl: "← Lewo",            en: "← Left" },
    btn_right:       { pl: "Prawo →",           en: "Right →" },
    shortcuts_hint:  { pl: "Skróty",            en: "Shortcuts" },
    shortcuts_tail:  { pl: "lub strzałki; Spacja = stop.", en: "or arrow keys; Space = stop." },
    balance:         { pl: "Stabilizacja", en: "Balance" },
    height:          { pl: "Wysokość", en: "Height" },
    follow_face:     { pl: "Śledź Twarz (Follow Face)", en: "Follow Face" },
    follow_hand:     { pl: "Śledź Dłoń (Follow Hand)", en: "Follow Hand" },
    recon_mode:      { pl: "Tryb rekonesansu (autonomiczny)", en: "Recon mode (autonomous)" },
    recon_strategy:  { pl: "Strategia", en: "Strategy" },
    return_home:     { pl: "🏠 Powrót do bazy", en: "🏠 Return Home" },
    features_title:  { pl: "Funkcje", en: "Features" },
    feature_face_desc:{ pl: "Uruchamia tracker oraz kontroler ruchu w trybie twarzy.", en: "Starts tracker + motion controller in face mode." },
    feature_hand_desc:{ pl: "Używa tych samych usług, ustawiając tryb dłoni.", en: "Uses the same services but switches to hand mode." },
    feature_recon_desc:{ pl: "Włącza usługi rekonesansu i wydaje polecenia navigatorowi.", en: "Turns on reconnaissance services and commands the navigator." },
    feature_btn_start:{ pl: "Start", en: "Start" },
    feature_btn_stop: { pl: "Stop", en: "Stop" },
    feature_status_running: { pl: "aktywne", en: "running" },
    feature_status_stopped: { pl: "wyłączone", en: "stopped" },
    feature_status_warn:    { pl: "wymaga uwagi", en: "check" },
    feature_status_error:   { pl: "błąd", en: "error" },
    feature_status_unknown: { pl: "n/d", en: "n/a" },
    feature_status_working: { pl: "w toku…", en: "working…" },
    feature_note_mode:      { pl: "tryb: {mode}", en: "mode: {mode}" },
    feature_note_state:     { pl: "stan: {state}", en: "state: {state}" },
    feature_note_missing_services: { pl: "brak usług: {count}", en: "missing services: {count}" },
    feature_note_missing_support:  { pl: "brak usług pomocniczych: {count}", en: "support services missing: {count}" },
    feature_note_waiting:   { pl: "czekam na wykonanie…", en: "waiting for sequence…" },
    feature_note_need_preview: { pl: "Wymagany podgląd CAM (rider-cam-preview).", en: "CAM preview service (rider-cam-preview) must be running." },
    feature_note_preview_forced: { pl: "CAM zastąpił: {name}", en: "CAM preview forced (replaced {name})." },
    feature_error_camera_feed: { pl: "Brak świeżego podglądu CAM (sprawdź rider-cam-preview).", en: "Camera feed is stale (check rider-cam-preview)." },
    feature_error_tracker_feed: { pl: "Brak świeżego podglądu TRACKER (sprawdź rider-tracker).", en: "Tracker feed is stale (check rider-tracker)." },
    preview_cam:  { pl: "CAM", en: "CAM" },
    preview_edge: { pl: "EDGE", en: "EDGE" },
    preview_ssd:  { pl: "PROC/SSD", en: "PROC/SSD" },
  },

  resources: {
    title:           { pl: "Diagnostyka zasobów", en: "Resource diagnostics" },
    column_name:     { pl: "Zasób", en: "Resource" },
    column_status:   { pl: "Status", en: "Status" },
    column_holders:  { pl: "Blokujące procesy", en: "Blocking processes" },
    column_actions:  { pl: "Akcje", en: "Actions" },
    mic:             { pl: "Mikrofon", en: "Microphone" },
    speaker:         { pl: "Głośnik", en: "Speaker" },
    camera:          { pl: "Kamera", en: "Camera" },
    lcd:             { pl: "Ekran LCD 2\"", en: "2\" LCD display" },
    btn_stop_service:{ pl: "Stop usługi", en: "Stop service" },
    btn_release:     { pl: "Zwolnij", en: "Release" },
    status_free:     { pl: "wolny", en: "free" },
    status_busy:     { pl: "zajęty", en: "busy" },
    status_error:    { pl: "błąd", en: "error" },
    holders_none:    { pl: "brak blokad", en: "no holders" },
    last_update:     { pl: "Ostatnia aktualizacja: {time}", en: "Last update: {time}" },
  },

  motion_queue: {
    title:               { pl: "Kolejka ruchu", en: "Motion queue" },
    btn_flush:           { pl: "⏹ stop & wyczyść", en: "⏹ stop & clear" },
    column_source:       { pl: "Źródło", en: "Source" },
    column_vx:           { pl: "Vx", en: "Vx" },
    column_vy:           { pl: "Vy", en: "Vy" },
    column_yaw:          { pl: "Yaw", en: "Yaw" },
    column_time:         { pl: "Czas [s]", en: "Time [s]" },
    column_status:       { pl: "Status", en: "Status" },
    column_age:          { pl: "Wiek", en: "Age" },
    loading:             { pl: "Brak danych…", en: "No data yet…" },
    empty_placeholder:   { pl: "Brak zleceń ruchu.", en: "No motion commands." },
    empty_state:         { pl: "Kolejka pusta", en: "Queue empty" },
    last_update:         { pl: "Ostatnia aktualizacja: {time}", en: "Last update: {time}" },
    note_cleared:        { pl: "Kolejka wyczyszczona", en: "Queue cleared" },
    note_cleared_reason: { pl: "Kolejka wyczyszczona ({reason})", en: "Queue cleared ({reason})" },
    status_queued:       { pl: "oczekuje", en: "queued" },
    status_executing:    { pl: "wykonywanie", en: "executing" },
    status_done:         { pl: "wykonane", en: "done" },
    status_skipped:      { pl: "odrzucone", en: "skipped" },
    status_stopped:      { pl: "zatrzymane", en: "stopped" },
    status_cleared:      { pl: "wyczyszczone", en: "cleared" },
    note_bridge_rx:      { pl: "bridge: rx", en: "bridge: rx" },
    note_reason:         { pl: "powód: {reason}", en: "reason: {reason}" },
    note_done:           { pl: "wykonano: {dir}", en: "performed: {dir}" },
    note_bridge_stop:    { pl: "mostek zatrzymał", en: "bridge stopped" },
    note_auto_stop:      { pl: "auto-stop", en: "auto-stop" },
    note_auto_stop_secs: { pl: "auto-stop ({secs}s)", en: "auto-stop ({secs}s)" },
    note_cmd_stop:       { pl: "cmd.stop", en: "cmd.stop" },
    reason_manual:       { pl: "panel", en: "panel" },
    reason_tracking:     { pl: "tracking", en: "tracking" },
  },

  services: {
    title:     { pl: "Usługi (systemd)", en: "Services (systemd)" },
    refresh:   { pl: "⟳ odśwież",       en: "⟳ refresh" },
    unit:      { pl: "Unit",            en: "Unit" },
    desc:      { pl: "Opis",            en: "Description" },
    status:    { pl: "Status",          en: "Status" },
    autostart: { pl: "Autostart",       en: "Autostart" },
    actions:   { pl: "Akcje",           en: "Actions" },

    btn_start:   { pl: "Start",   en: "Start" },
    btn_stop:    { pl: "Stop",    en: "Stop" },
    btn_restart: { pl: "Restart", en: "Restart" },
    btn_enable:  { pl: "Enable",  en: "Enable" },
    btn_disable: { pl: "Disable", en: "Disable" },

    empty:       { pl: "Brak danych o usługach.", en: "No service data." },
    error_fetch: { pl: "Błąd pobierania listy usług: {msg}", en: "Failed to fetch services: {msg}" },
    log_action:  { pl: "systemd[{action} {unit}] → kod: {code} · {msg}", en: "systemd[{action} {unit}] → code: {code} · {msg}" },
    status_active:  { pl: "aktywna", en: "active" },
    status_starting:{ pl: "uruchamianie", en: "starting" },
    status_stopping:{ pl: "zatrzymywanie", en: "stopping" },
    status_inactive:{ pl: "nieaktywna", en: "inactive" },
    status_failed:  { pl: "błąd", en: "failed" },
    status_unknown: { pl: "nieznany", en: "unknown" },
    autostart_enabled:  { pl: "włączony", en: "enabled" },
    autostart_disabled: { pl: "wyłączony", en: "disabled" },
    autostart_static:   { pl: "statyczny", en: "static" },
    autostart_linked:   { pl: "powiązany", en: "linked" },
    autostart_masked:   { pl: "zamaskowany", en: "masked" },
    autostart_generated:{ pl: "generowany", en: "generated" },
    autostart_indirect: { pl: "pośredni", en: "indirect" },
    autostart_unknown:  { pl: "nieznany", en: "unknown" },
  },

  events: {
    title:         { pl: "Zdarzenia (SSE /events)", en: "Events (SSE /events)" },
    log_js_err:    { pl: "Błąd JS: {msg}",         en: "JS error: {msg}" },
    log_prom_err:  { pl: "Błąd obietnicy: {reason}", en: "Promise error: {reason}" },
    sse_connected: { pl: "Połączono z /events",    en: "Connected to /events" },
    generic_event: { pl: "zdarzenie",             en: "event" },
    sse_reconnect: { pl: "Błąd SSE — ponawiam połączenie…", en: "SSE error — reconnecting…" },
    sse_init_err:  { pl: "Błąd inicjalizacji SSE: {err}",   en: "SSE init error: {err}" },
  },

  // ===== GOOGLE HOME =====
  home: {
    page_title:         { pl: "Rider-Pi — Sterowanie Google Home", en: "Rider-Pi — Google Home Control" },
    auth_checking:      { pl: "Sprawdzanie…", en: "Checking…" },
    auth_ok:            { pl: "Zalogowano", en: "Authenticated" },
    auth_required:      { pl: "Wymagane logowanie", en: "Auth Required" },
    auth_error:         { pl: "Błąd autoryzacji", en: "Auth Error" },
    auth_title:         { pl: "Wymagana autoryzacja", en: "Authentication Required" },
    auth_description:   { pl: "Aby sterować urządzeniami Google Home, zaloguj się kontem Google.", en: "To control your Google Home devices, please sign in with your Google account." },
    auth_button:        { pl: "Zaloguj przez Google", en: "Sign in with Google" },
    auth_success:       { pl: "Zalogowano pomyślnie!", en: "Authentication successful!" },
    devices_title:      { pl: "Twoje urządzenia", en: "Your Devices" },
    refresh_button:     { pl: "⟳ Odśwież", en: "⟳ Refresh" },
    no_devices:         { pl: "Brak urządzeń. Sprawdź konfigurację Google Home.", en: "No devices found. Check your Google Home configuration." },
    btn_on:             { pl: "Włącz", en: "On" },
    btn_off:            { pl: "Wyłącz", en: "Off" },
    brightness:         { pl: "Jasność", en: "Brightness" },
    color_temperature:  { pl: "Temperatura barwowa", en: "Color Temperature" },
    color:              { pl: "Kolor", en: "Color" },
    temperature_setpoint: { pl: "Temperatura zadana", en: "Temperature Setpoint" },
    temperature_ambient:  { pl: "Temperatura otoczenia", en: "Ambient Temperature" },
    thermostat_mode:      { pl: "Tryb termostatu", en: "Thermostat Mode" },
    mode_off:           { pl: "Wyłączony", en: "Off" },
    mode_heat:          { pl: "Ogrzewanie", en: "Heat" },
    mode_cool:          { pl: "Chłodzenie", en: "Cool" },
    mode_heatcool:      { pl: "Auto", en: "Auto" },
    mode_eco:           { pl: "Eco", en: "Eco" },
    mode_on:            { pl: "Włączony", en: "On" },
    btn_start:          { pl: "Start", en: "Start" },
    btn_stop:           { pl: "Stop", en: "Stop" },
    btn_pause:          { pl: "Pauza", en: "Pause" },
    btn_dock:           { pl: "Wróć do bazy", en: "Return to Dock" },
    sending_command:    { pl: "Wysyłanie komendy…", en: "Sending command…" },
    command_success:    { pl: "Komenda wykonana pomyślnie", en: "Command executed successfully" },
    error_check_auth:   { pl: "Błąd sprawdzania autoryzacji: {msg}", en: "Error checking auth: {msg}" },
    error_load_devices: { pl: "Błąd ładowania urządzeń: {msg}", en: "Error loading devices: {msg}" },
    error_send_command: { pl: "Błąd wysyłania komendy: {msg}", en: "Error sending command: {msg}" },
    error_auth:         { pl: "Błąd autoryzacji: {msg}", en: "Authentication error: {msg}" },
    error_timeout:      { pl: "Przekroczono czas oczekiwania na autoryzację. Spróbuj ponownie.", en: "Authentication timeout. Please try again." },
  },

  // ===== AI MODE =====
  ai_mode: {
    title:              { pl: "Tryb AI", en: "AI Mode" },
    description:        { pl: "Wybierz tryb przetwarzania AI: lokalny (wszystko na Pi) lub offload (ciężkie obliczenia na PC).", en: "Choose AI processing mode: local (all on Pi) or offload (heavy processing on PC)." },
    loading:            { pl: "ładowanie…", en: "loading…" },
    mode_local:         { pl: "🏠 Local (Pi)", en: "🏠 Local (Pi)" },
    mode_offload:       { pl: "💻 PC Offload", en: "💻 PC Offload" },
    btn_local:          { pl: "🏠 Local (Pi)", en: "🏠 Local (Pi)" },
    btn_offload:        { pl: "💻 PC Offload", en: "💻 PC Offload" },
    status_checking:    { pl: "sprawdzanie…", en: "checking…" },
    status_active:      { pl: "aktywny: {mode}", en: "active: {mode}" },
    status_error:       { pl: "błąd: {error}", en: "error: {error}" },
    last_changed:       { pl: "Ostatnia zmiana:", en: "Last changed:" },
  },

  provider: {
    title:                { pl: "Provider Control", en: "Provider Control" },
    description:          { pl: "Przełączaj źródło przetwarzania (lokalnie na Pi lub na komputerze PC).", en: "Switch processing source (local on Pi or offloaded to the PC)." },
    btn_local:            { pl: "🏠 Local (Pi)", en: "🏠 Local (Pi)" },
    btn_pc:               { pl: "💻 PC Offload", en: "💻 PC Offload" },
    pc_status_unknown:    { pl: "PC: status nieznany", en: "PC: status unknown" },
    pc_status_pending:    { pl: "PC: oczekiwanie", en: "PC: pending" },
    pc_status_online:     { pl: "PC: online", en: "PC: online" },
    pc_status_offline:    { pl: "PC: offline", en: "PC: offline" },
    mode_local:           { pl: "Lokalny", en: "Local" },
    mode_pc:              { pl: "PC", en: "PC" },
    status_local_only:    { pl: "Tylko lokalnie", en: "Local only" },
    status_pc_pending:    { pl: "PC: oczekiwanie", en: "PC pending" },
    status_pc_active:     { pl: "PC: aktywny", en: "PC active" },
    status_fallback:      { pl: "Fallback na lokalny", en: "Fallback to local" },
    status_unknown:       { pl: "Status nieznany", en: "Unknown status" },
    changed_label:        { pl: "Ostatnia zmiana:", en: "Last change:" },
    changed_unknown:      { pl: "n/d", en: "n/a" },
    domain_vision:        { pl: "Vision", en: "Vision" },
    domain_voice:         { pl: "Voice", en: "Voice" },
    domain_text:          { pl: "Text / LLM", en: "Text / LLM" },
    domain_vision_desc:   { pl: "Detekcja przeszkód, przetwarzanie obrazu.", en: "Obstacle detection, vision processing." },
    domain_voice_desc:    { pl: "ASR / TTS, komendy głosowe i rozmowy.", en: "ASR / TTS, voice commands and chat." },
    domain_text_desc:     { pl: "LLM, odpowiedzi tekstowe i generowanie komend.", en: "LLM, textual replies and command generation." },
  },
};

let CURRENT_LANG = 'pl';
function fmt(str, params) {
  if (!params) return str;
  return str.replace(/\{(\w+)\}/g, (_, k) => (k in params ? String(params[k]) : `{${k}}`));
}
export function t(key, params) {
  const segs = key.split('.');
  let node = I18N;
  for (const s of segs) { node = node?.[s]; if (!node) return key; }
  const val = node[CURRENT_LANG] ?? node['en'] ?? key;
  return fmt(val, params);
}
export function applyDom(root = document) {
  root.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    let params = {};
    const raw = el.getAttribute('data-i18n-params');
    if (raw) { try { params = JSON.parse(raw); } catch {} }
    el.textContent = t(key, params);
  });
  root.querySelectorAll('[data-i18n-attr]').forEach(el => {
    const spec = el.getAttribute('data-i18n-attr');
    spec.split(',').forEach(pair => {
      const [attr, key] = pair.split(':').map(s => s.trim());
      if (attr && key) el.setAttribute(attr, t(key));
    });
  });
}
export function getLang() {
  return CURRENT_LANG;
}
function emitLangChange(lang){
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') return;
  if (typeof CustomEvent === 'function') {
    window.dispatchEvent(new CustomEvent('dashboard:langchange', { detail: { lang } }));
  } else if (typeof document !== 'undefined' && typeof document.createEvent === 'function') {
    const evt = document.createEvent('CustomEvent');
    evt.initCustomEvent('dashboard:langchange', false, false, { lang });
    window.dispatchEvent(evt);
  }
}
export function setLang(lang) {
  CURRENT_LANG = (lang === 'en') ? 'en' : 'pl';
  applyDom(document);
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.setAttribute('lang', CURRENT_LANG);
  }
  emitLangChange(CURRENT_LANG);
}
export function initI18n(lang = 'pl') {
  setLang(lang);
  window.i18n = { t, setLang, applyDom, getLang };
}
