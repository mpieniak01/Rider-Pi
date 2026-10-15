import { RemoteNavigation } from "./remote-navigation.js";
import { CameraPower } from './camera-power.js?v=overview-vision-2';
import { Posture } from './posture.js?v=posture-1';
import { ManualSettings } from './manual-settings.js?v=motion-curves-14';
import { ControlCamera } from './control-camera.js?v=control-restored-1';
import { initI18n } from '/web/assets/i18n.js';
import { SafetyPanel } from './safety.js?v=motion-descriptors-9';
import { Tasks } from './tasks.js?v=compact-calibration-4b';
import { Devices } from './devices.js?v=camera-preview-1';
import { System } from './system.js?v=system-controls-1';
import { Navigation } from './navigation.js';
import { Calibration } from './calibration.js?v=compact-calibration-4b';
import { Chat } from './chat.js?v=compact-calibration-4b';
import { Overview } from './overview.js?v=extended-telemetry-1';
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
let posture, tasks, system, navigation, chat, calibration, overview, lastKey = '';
const safety = new SafetyPanel(state => {
  const key = JSON.stringify([state?.state, state?.generation, state?.can_move, state?.ready, state?.hardware_ready, state?.capabilities,
    fresh(state), safety.clockFresh(), safety.revokedGenerations.has(state?.generation), ['manual', 'follow_me', 'navigation'].map(owner => safety.can(owner))]);
  if (key !== lastKey) { lastKey = key; tasks?.render(); system?.render(); }
  navigation?.render(); calibration?.render(); posture?.render(); overview?.renderTelemetry();
  renderCapabilities(state);
}, { interactive: motionPage });
if (['control', 'calibration'].includes(page)) safety.controls = new ManualSettings(safety);
if (['control', 'calibration'].includes(page)) posture = new Posture(safety);
if (page === 'control') new ControlCamera();

if (page === 'control') tasks = new Tasks(safety);
if (page === 'calibration') calibration = new Calibration(safety);
if (page === 'devices') new Devices(safety);
if (page === 'system') system = new System(safety);
if (page === 'navigation') { new RemoteNavigation(safety); tasks = new Tasks(safety, 'task-list', task => task.can_move === false && (task.motion_owner === 'navigation' || task.scenario === 'S8')); navigation = new Navigation(safety); }
if (page === 'chat') { tasks = new Tasks(safety, 'task-list', task => ['voice', 'provider'].includes(task.option_kind) && task.can_move === false); chat = new Chat(tasks); }
if (page === 'view') {
  overview = new Overview(safety);
  const refreshVision = () => { overview.snap = null; overview.renderVision(); overview.poller.refresh(); overview.visionPoller.refresh(); };
  const raw = new CameraPower({ onStarted: refreshVision, onStopped: refreshVision, label: '' });
  const processed = new CameraPower({ taskName: 's7_obstacle_module', options: { provider: 'local' },
    toggleIds: ['camera-proc-toggle', 'camera-obst-toggle'], statusIds: ['camera-proc-state', 'camera-obst-state'],
    startId: null, stopId: null, label: '', onStarted: refreshVision, onStopped: refreshVision });
  const tracker = new CameraPower({ taskName: 's6_tracker_module', options: { mode: 'face' },
    toggleIds: ['camera-tracker-toggle'], statusIds: ['camera-tracker-state'], startId: null, stopId: null,
    label: '', onStarted: refreshVision, onStopped: refreshVision });
  for (const control of [raw, processed, tracker]) {
    const started = control.onStarted, stopped = control.onStopped;
    const refreshControls = () => { for (const other of [raw, processed, tracker]) if (other !== control) other.poller.refresh(); };
    control.onStarted = () => { started(); refreshControls(); };
    control.onStopped = () => { stopped(); refreshControls(); };
  }

}

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
    row.textContent = `${action}: ${cap?.available === true && (['height', 'balance'].includes(action) || cap?.stop_verified === true) ? tr('dostępne po uzbrojeniu', 'available after arming') : cap?.verification === 'manual_characterization_required' ? tr('blokada — wymagana ręczna charakterystyka i przerwanie ruchu', 'blocked — manual characterization and interruption required') : tr('niedostępne / niepotwierdzone', 'unavailable / unverified')}`;
    return row;
  }));
  }
  document.querySelectorAll('[data-actuator]').forEach(node => { node.disabled = !safety.can('manual', node.dataset.actuator); });
}
window.addEventListener('dashboard:langchange', () => { localizeStatic(); lastKey = ''; safety.render(); tasks?.render(); system?.render(); navigation?.render(); calibration?.render(); });
if (chat) setInterval(() => { if (!chat.busy) document.getElementById('chat-send').disabled = !catalogKnown(tasks.catalog); }, 1000);
