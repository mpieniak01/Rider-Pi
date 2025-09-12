// web/i18n.js
export const I18N = {
  meta: {
    app_title: { pl: "Rider-Pi — Sterowanie ruchem (REST /api)", en: "Rider-Pi — Motion Control (REST /api)" },
    loading:   { pl: "Ładowanie…", en: "Loading…" },
    ok:        { pl: "OK", en: "OK" },
    warn:      { pl: "Ostrzeżenie", en: "Warning" },
    error:     { pl: "Błąd", en: "Error" },
  },
  header: {
    api_status_checking: { pl: "(sprawdzanie…)", en: "(checking…)" },
    api_status_ok:       { pl: "ok", en: "ok" },
    api_status_degraded: { pl: "ograniczone", en: "degraded" },
    api_status_down:     { pl: "niedostępne", en: "down" },
  },
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
    },

    camera_proc: {
      title:   { pl: "Kamera — PROC", en: "Camera — PROC" },
      caption: { pl: "ramki / etykiety", en: "boxes / labels" },
    },

    status: {
      vision_prefix: { pl: "VISION:", en: "VISION:" },
      present:       { pl: "PRESENT", en: "PRESENT" },
      idle:          { pl: "IDLE",    en: "IDLE" },
      mode:          { pl: "mode",    en: "mode" },
      conf:          { pl: "conf",    en: "conf" },
      cam_prefix:    { pl: "CAM:",    en: "CAM:" }
    }
  }
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
