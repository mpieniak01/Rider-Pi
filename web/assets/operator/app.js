import { ControlCamera } from './control-camera.js?v=control-restored-1';
import { initI18n } from '/web/assets/i18n.js';
import { SafetyPanel } from './safety.js?v=global-motion-1';
import { Tasks } from './tasks.js?v=global-motion-1';
import { Devices } from './devices.js';
import { System } from './system.js?v=global-motion-1';
import { Navigation } from './navigation.js';
import { Calibration } from './calibration.js?v=global-motion-1';
import { Chat } from './chat.js?v=global-motion-1';
import { Overview } from './overview.js';
import { events } from './transport.js';
import { fresh, catalogKnown, safetyKnown, nowSeconds } from './model.js';
import { el, text, tr, localizeStatic, refreshAges, showError } from './ui.js';

initI18n(localStorage.getItem('lang') || 'pl'); localizeStatic();
setInterval(refreshAges, 1000);
const page = document.body.dataset.page;
const motionPage = ['control', 'calibration', 'system'].includes(page);
const motionToggle = el('button', 'c-btn operator-motion-toggle is-disarmed');
motionToggle.id = 'global-motion-toggle'; motionToggle.type = 'button';
motionToggle.textContent = tr('Robot rozbrojony', 'Robot disarmed');
motionToggle.disabled = true; motionToggle.setAttribute('aria-pressed', 'false');
document.querySelector('main').append(motionToggle);
let tasks, system, navigation, chat, calibration, overview, lastKey = '';
const safety = new SafetyPanel(state => {
  const key = JSON.stringify([state?.state, state?.generation, state?.can_move, state?.ready, state?.hardware_ready, state?.capabilities,
    fresh(state), safety.clockFresh(), safety.revokedGenerations.has(state?.generation), ['manual', 'follow_me', 'navigation'].map(owner => safety.can(owner))]);
  if (key !== lastKey) { lastKey = key; tasks?.render(); system?.render(); }
  navigation?.render(); calibration?.render(); overview?.renderTelemetry();
  renderCapabilities(state);
}, { interactive: motionPage });
if (['control', 'calibration'].includes(page)) new ControlCamera();
if (page === 'control') loadControlTuning();
if (page === 'control') tasks = new Tasks(safety);
if (page === 'calibration') calibration = new Calibration(safety);
if (page === 'devices') new Devices();
if (page === 'system') system = new System(safety);
if (page === 'navigation') { tasks = new Tasks(safety, 'task-list', task => task.can_move === false && (task.motion_owner === 'navigation' || task.scenario === 'S8')); navigation = new Navigation(safety); }
if (page === 'chat') { tasks = new Tasks(safety, 'task-list', task => ['voice', 'provider'].includes(task.option_kind) && task.can_move === false); chat = new Chat(tasks); }
if (page === 'view') overview = new Overview(safety);

events(event => {
  let data = event.data;
  try { if (typeof data === 'string') data = JSON.parse(data); } catch { navigation?.event(event); return; }
  if (event.topic === 'motion.state' && data?.contract_version === 1) safety.update(data);
  if (event.topic === 'motion.ack') safety.ack(data);
  navigation?.event(event);
  text('last-event', `${event.topic || '?'} · ${event.ts ?? '—'}`);
}, () => text('last-event', tr('Strumień zdarzeń niedostępny; odczyt okresowy aktywny', 'Event stream unavailable; periodic reads active')));

function renderCapabilities(state) {
  const target = document.getElementById('actuator-capabilities'); if (!target) return;
  const known = safetyKnown(state);
  const key = JSON.stringify([state?.capabilities, known, state?.state, state?.can_move]);
  if (target.dataset.key !== key) {
  target.dataset.key = key;
  target.replaceChildren(...['move', 'turn', 'balance', 'height', 'action'].map(action => {
    const cap = known ? state?.capabilities?.[action] : null; const row = el('li');
    row.textContent = `${action}: ${cap?.available === true && cap?.stop_verified === true ? tr('dostępne po uzbrojeniu', 'available after arming') : cap?.verification === 'manual_characterization_required' ? tr('blokada — wymagana ręczna charakterystyka i przerwanie ruchu', 'blocked — manual characterization and interruption required') : tr('niedostępne / niepotwierdzone', 'unavailable / unverified')}`;
    return row;
  }));
  }
  document.querySelectorAll('[data-actuator]').forEach(node => { node.disabled = !safety.can('manual', node.dataset.actuator); });
}
const numberInput = id => { const value = document.getElementById(id)?.value.trim(); return value ? Number(value) : NaN; };
document.getElementById('height-apply')?.addEventListener('click', () => safety.send('height', { height: numberInput('height') }).catch(showError));
document.getElementById('balance-apply')?.addEventListener('click', () => safety.send('balance', { enabled: document.getElementById('balance').checked }).catch(showError));
document.getElementById('action-apply')?.addEventListener('click', () => safety.send('action', { action_id: numberInput('action-id') }).catch(showError));
window.addEventListener('dashboard:langchange', () => { localizeStatic(); lastKey = ''; safety.render(); tasks?.render(); system?.render(); navigation?.render(); calibration?.render(); });
if (chat) setInterval(() => { if (!chat.busy) document.getElementById('chat-send').disabled = !catalogKnown(tasks.catalog); }, 1000);


// Fetch shared Pi defaults once; never overwrite settings the operator has touched.
async function loadControlTuning() {
  const touched = new Set();
  for (const id of ['speed', 'yaw-speed', 'duration']) {
    document.getElementById(id)?.addEventListener('input', () => touched.add(id));
  }
  try {
    const [{ request }, { interactionValid, freshCalibration }] = await Promise.all([
      import('./transport.js'), import('./calibration-model.js?v=calibration-tuning-1')
    ]);
    const state = (await request('/api/calibration/state')).data, motion = state?.motion;
    const tuning = motion?.calibration?.interaction;
    if (!freshCalibration(motion, nowSeconds()) || motion.calibration?.error || !interactionValid(tuning)) return;
    for (const [id, key] of [['speed', 'linear_speed'], ['yaw-speed', 'turn_speed'], ['duration', 'pulse_duration']]) {
      const node = document.getElementById(id);
      if (node && !touched.has(id)) { node.value = tuning[key]; node.dispatchEvent(new Event('input')); }
    }
  } catch { /* Read failure keeps existing controls; it never enables motion. */ }
}
