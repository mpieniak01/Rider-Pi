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
    turning_range:   { pl: "(0..1)",           en: "(0..1)" },
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
export function setLang(lang) {
  CURRENT_LANG = (lang === 'en') ? 'en' : 'pl';
  applyDom(document);
}
export function initI18n(lang = 'pl') {
  setLang(lang);
  window.i18n = { t, setLang, applyDom };
}
