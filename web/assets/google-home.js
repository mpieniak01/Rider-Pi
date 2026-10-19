import { initI18n, applyDom, t } from './i18n.js';

const DEFAULT_COLOR_TEMP_K = 3000;
const DEFAULT_RGB_COLOR = 0xFFFFFF;
const DEFAULT_TEMPERATURE_C = 20;
const TEMP_INCREMENT_C = 0.5;
const qs = selector => document.querySelector(selector);

function pickLanguage(value) {
  const code = value?.toLowerCase();
  if (code?.startsWith('en')) return 'en';
  if (code?.startsWith('pl')) return 'pl';
  return null;
}
const urlLang = new URLSearchParams(location.search).get('lang');
const saved = localStorage.getItem('lang');
const browser = (navigator.language || '').slice(0, 2).toLowerCase();
const lang = pickLanguage(urlLang) || pickLanguage(saved) || pickLanguage(browser) || 'pl';
if (urlLang) localStorage.setItem('lang', lang);
initI18n(lang);
applyDom();
function syncLangMeta(code) {
  document.documentElement.setAttribute('lang', code);
  document.title = t('home.page_title');
}
syncLangMeta(lang);
window.addEventListener('dashboard:langchange', event => {
  const next = event?.detail?.lang;
  if (next) syncLangMeta(next);
});

function node(tag, className = '', value) {
  const result = document.createElement(tag);
  result.className = className;
  if (value !== undefined) result.textContent = String(value);
  return result;
}
function showStatus(message, type = 'ok') {
  const status = qs('#statusMsg');
  status.textContent = message;
  status.className = 'c-status-msg ' + type;
  status.classList.remove('hidden');
  setTimeout(() => status.classList.add('hidden'), 5000);
}
function showReadError(error) {
  showStatus(t('home.error_load_devices', {msg: error.message}), 'err');
}
async function httpGet(url) {
  const response = await fetch(url, {cache: 'no-store'});
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || 'HTTP ' + response.status);
  return result;
}
async function httpPost(url, body) {
  const response = await fetch(url, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || 'HTTP ' + response.status);
  return result;
}
async function checkAuth() {
  try {
    const result = await httpGet('/api/home/status');
    const badge = qs('#authBadge');
    const auth = qs('#authSection');
    const devices = qs('#devicesSection');
    if (result.authenticated) {
      badge.textContent = t('home.auth_ok');
      badge.className = 'c-pill ok';
      auth.classList.add('hidden');
      devices.classList.remove('hidden');
      // Keep device loading independent from auth completion and report any rejection.
      loadDevices().catch(showReadError);
    } else {
      badge.textContent = t('home.auth_required');
      badge.className = 'c-pill warn';
      auth.classList.remove('hidden');
      devices.classList.add('hidden');
    }
  } catch (error) {
    const badge = qs('#authBadge');
    badge.textContent = t('home.auth_error');
    badge.className = 'c-pill err';
    showStatus(t('home.error_check_auth', {msg: error.message}), 'err');
  }
}
async function loadDevices() {
  const list = qs('#devicesList');
  const loading = node('div', 'muted');
  loading.append(node('span', 'spinner'), node('span', '', t('meta.loading')));
  list.replaceChildren(loading);
  try {
    const result = await httpGet('/api/home/devices');
    if (!result.ok) throw new Error(result.error || 'Failed to load devices');
    const devices = result.devices || [];
    if (devices.length === 0) {
      const empty = node('div', 'note', t('home.no_devices'));
      empty.dataset.i18n = 'home.no_devices';
      list.replaceChildren(empty);
      return;
    }
    list.replaceChildren();
    devices.forEach(device => renderDevice(device));
  } catch (error) {
    list.replaceChildren(node('div', 'err', t('home.error_load_devices', {msg: error.message})));
  }
}

function finiteNumber(value, fallback) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}
function boundedNumber(value, fallback, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, finiteNumber(value, fallback)));
}
function controlRow(...children) {
  const row = node('div', 'control-row');
  row.append(...children);
  return row;
}
function labelled(key, ...children) {
  const label = node('label', 'control-label');
  label.append(node('span', '', t(key) + ':'), ...children);
  return controlRow(label);
}
function commandButton(device, action, key, command, params) {
  const button = node('button', 'c-btn-sm', t(key));
  button.dataset.action = action;
  button.dataset.device = device.name;
  button.addEventListener('click', () => sendCommand(device.name, command, params));
  return button;
}
function rangeControl(device, action, value, minimum, maximum) {
  const input = node('input');
  input.type = 'range';
  input.min = String(minimum);
  input.max = String(maximum);
  input.value = String(boundedNumber(value, minimum, minimum, maximum));
  input.dataset.action = action;
  input.dataset.device = device.name;
  return input;
}
function onOffControls(device, trait) {
  return controlRow(
    commandButton(device, 'on', 'home.btn_on', 'action.devices.commands.OnOff', {on: true}),
    commandButton(device, 'off', 'home.btn_off', 'action.devices.commands.OnOff', {on: false}),
    node('span', 'muted', trait.on ? '(ON)' : '(OFF)'),
  );
}
function brightnessControls(device, trait) {
  const value = boundedNumber(trait.brightness, 0, 0, 100);
  const input = rangeControl(device, 'brightness', value, 0, 100);
  const label = node('span', 'brightness-value', value + '%');
  input.addEventListener('change', event => {
    const brightness = Number.parseInt(event.target.value);
    return sendCommand(device.name, 'action.devices.commands.BrightnessAbsolute', {brightness});
  });
  input.addEventListener('input', event => { label.textContent = event.target.value + '%'; });
  return labelled('home.brightness', input, label);
}
function colorControls(device, trait) {
  const rows = [];
  if (trait.temperatureK !== undefined) {
    const value = boundedNumber(trait.temperatureK || DEFAULT_COLOR_TEMP_K, DEFAULT_COLOR_TEMP_K, 2000, 6500);
    const input = rangeControl(device, 'color-temp', value, 2000, 6500);
    const label = node('span', 'color-temp-value', value + 'K');
    input.addEventListener('change', event => {
      const temperatureK = Number.parseInt(event.target.value);
      return sendCommand(device.name, 'action.devices.commands.ColorAbsolute', {color: {temperatureK}});
    });
    input.addEventListener('input', event => { label.textContent = event.target.value + 'K'; });
    rows.push(labelled('home.color_temperature', input, label));
  }
  if (trait.spectrumRgb !== undefined) {
    const value = Math.trunc(boundedNumber(trait.spectrumRgb || DEFAULT_RGB_COLOR, DEFAULT_RGB_COLOR, 0, 0xFFFFFF));
    const input = node('input');
    input.type = 'color';
    input.value = '#' + value.toString(16).padStart(6, '0');
    input.dataset.action = 'color-rgb';
    input.dataset.device = device.name;
    input.addEventListener('change', event => {
      const spectrumRgb = Number.parseInt(event.target.value.substring(1), 16);
      return sendCommand(device.name, 'action.devices.commands.ColorAbsolute', {color: {spectrumRgb}});
    });
    rows.push(labelled('home.color', input));
  }
  return rows;
}
function temperatureButton(device, action, delta, value) {
  const button = node('button', 'c-btn-sm', delta > 0 ? '+' : '−');
  button.dataset.action = action;
  button.dataset.device = device.name;
  button.addEventListener('click', () => {
    const current = Number.parseFloat(value.textContent) || DEFAULT_TEMPERATURE_C;
    return sendCommand(device.name, 'action.devices.commands.ThermostatTemperatureSetpoint',
      {thermostatTemperatureSetpoint: current + delta});
  });
  return button;
}
function thermostatModes(device, trait) {
  const modes = Array.isArray(trait.availableThermostatModes) ? trait.availableThermostatModes : [];
  if (!modes.length) return null;
  const select = node('select');
  select.dataset.action = 'thermostat-mode';
  select.dataset.device = device.name;
  const current = trait.thermostatMode || 'off';
  for (const mode of modes) {
    if (typeof mode !== 'string') continue;
    const option = node('option', '', t('home.mode_' + mode));
    option.value = mode;
    option.selected = mode === current;
    select.append(option);
  }
  select.addEventListener('change', event => {
    return sendCommand(device.name, 'action.devices.commands.ThermostatSetMode', {thermostatMode: event.target.value});
  });
  return labelled('home.thermostat_mode', select);
}
function temperatureControls(device, trait) {
  const value = node('span', 'temp-value',
    finiteNumber(trait.thermostatTemperatureSetpoint || DEFAULT_TEMPERATURE_C, DEFAULT_TEMPERATURE_C) + '°C');
  const rows = [labelled('home.temperature_setpoint',
    temperatureButton(device, 'temp-down', -TEMP_INCREMENT_C, value), value,
    temperatureButton(device, 'temp-up', TEMP_INCREMENT_C, value))];
  if (trait.thermostatTemperatureAmbient !== undefined) {
    rows.push(controlRow(node('span', 'muted', t('home.temperature_ambient') + ': ' + trait.thermostatTemperatureAmbient + '°C')));
  }
  const modes = thermostatModes(device, trait);
  if (modes) rows.push(modes);
  return rows;
}
function startStopControls(device, trait) {
  let status = 'STOPPED';
  if (trait.isRunning) status = trait.isPaused ? 'PAUSED' : 'RUNNING';
  return controlRow(
    commandButton(device, 'start', 'home.btn_start', 'action.devices.commands.StartStop', {start: true}),
    commandButton(device, 'stop', 'home.btn_stop', 'action.devices.commands.StartStop', {start: false}),
    commandButton(device, 'pause', 'home.btn_pause', 'action.devices.commands.PauseUnpause', {pause: true}),
    node('span', 'muted', '(' + status + ')'),
  );
}
function renderDevice(device) {
  const name = String(device.name || 'Unknown Device').split('/').pop() || 'Unknown Device';
  const traits = device.traits || {};
  const card = node('div', 'device-card c-card');
  const controls = node('div', 'device-controls');
  card.append(node('div', 'device-name', name), node('div', 'device-type', device.type || 'Unknown'), controls);
  if (traits['sdm.devices.traits.OnOff']) controls.append(onOffControls(device, traits['sdm.devices.traits.OnOff']));
  if (traits['sdm.devices.traits.Brightness']) controls.append(brightnessControls(device, traits['sdm.devices.traits.Brightness']));
  if (traits['sdm.devices.traits.ColorSetting']) controls.append(...colorControls(device, traits['sdm.devices.traits.ColorSetting']));
  if (traits['sdm.devices.traits.TemperatureSetting']) controls.append(...temperatureControls(device, traits['sdm.devices.traits.TemperatureSetting']));
  if (traits['sdm.devices.traits.StartStop']) controls.append(startStopControls(device, traits['sdm.devices.traits.StartStop']));
  if (traits['sdm.devices.traits.Dock']) controls.append(controlRow(commandButton(device, 'dock', 'home.btn_dock', 'action.devices.commands.Dock', {})));
  qs('#devicesList').appendChild(card);
}
async function sendCommand(deviceId, command, params) {
  try {
    showStatus(t('home.sending_command'), 'ok');
    const result = await httpPost('/api/home/command', {deviceId, command, params});
    if (!result.ok) throw new Error(result.error || 'Command failed');
    showStatus(t('home.command_success'), 'ok');
    setTimeout(() => loadDevices().catch(showReadError), 1500);
  } catch (error) {
    showStatus(t('home.error_send_command', {msg: error.message}), 'err');
  }
}
async function handleAuth(button) {
  if (!button) return;
  const originalText = button.textContent;
  let timeoutId;
  try {
    button.disabled = true;
    button.textContent = t('meta.loading') + '...';
    const controller = new AbortController();
    timeoutId = setTimeout(() => controller.abort(), 120000);
    const response = await fetch('/api/home/auth', {method: 'POST', signal: controller.signal});
    clearTimeout(timeoutId);
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || 'Authentication failed');
    showStatus(t('home.auth_success'), 'ok');
    await checkAuth();
  } catch (error) {
    const message = error.name === 'AbortError' ? t('home.error_timeout') : t('home.error_auth', {msg: error.message});
    showStatus(message, 'err');
  } finally {
    clearTimeout(timeoutId);
    button.disabled = false;
    button.textContent = originalText;
  }
}
document.querySelectorAll('[data-auth-trigger]').forEach(button => {
  button.addEventListener('click', () => handleAuth(button));
});
qs('#btnRefresh').addEventListener('click', () => loadDevices().catch(showReadError));
if (new URLSearchParams(location.search).get('auth') === 'success') {
  window.history.replaceState({}, '', location.pathname);
  showStatus(t('home.auth_success'), 'ok');
}
// Startup stays non-blocking; all network failures have a visible error path.
checkAuth().catch(error => showStatus(t('home.error_check_auth', {msg: error.message}), 'err'));
