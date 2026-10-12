import { catalogKnown, taskCanStart, fresh } from './model.js';
import { request, poll } from './transport.js';
import { text, tr, showError, powerLabel } from './ui.js';

const CAMERA_TASK = 's2_camera_preview';
// Explicit operator clicks only. Page entry and polling remain read-only.
export class CameraPower {
  constructor({ onStarted = () => {}, onStopped = () => {}, taskName = CAMERA_TASK, options = {},
    toggleIds = ['camera-toggle'], statusIds = ['camera-power-state'], label = 'Kamera',
    startId = 'camera-start', stopId = 'camera-stop' } = {}) {
    this.taskName = taskName; this.options = options; this.statusIds = statusIds; this.label = label;
    this.catalog = null; this.busy = false; this.onStarted = onStarted; this.onStopped = onStopped;
    this.start = document.getElementById(startId); this.stop = document.getElementById(stopId);
    this.toggles = toggleIds.map(id => document.getElementById(id)).filter(Boolean);
    for (const toggle of this.toggles) toggle.addEventListener('click', () => {
      if (this.known()) return this.change(this.task().requested !== true);
    });
    this.start?.addEventListener('click', () => this.change(true));
    this.stop?.addEventListener('click', () => this.change(false));
    this.poller = poll(() => this.load(), { profile: 'services', onError: error => {
      this.catalog = null; this.render(); showError(error);
    } });
    this.expiry = setInterval(() => this.render(), 1000);
    window.addEventListener('dashboard:langchange', () => this.render());
    window.addEventListener('pagehide', () => { this.poller.stop(); clearInterval(this.expiry); });
    this.render();
  }
  async load(force = false) {
    this.catalog = (await request('/api/logic/catalog', { force })).data; this.render();
  }
  task() { return this.catalog?.features?.find(task => task.name === this.taskName); }
  known() {
    const task = this.task();
    return catalogKnown(this.catalog) && task?.can_move === false && fresh(task, 10);
  }
  async change(enabled) {
    if (this.busy) return;
    this.busy = true; this.render();
    try {
      // Recheck the task immediately before an explicit start/stop.
      await this.load(true);
      const task = this.task();
      if (!this.known() || (enabled ? task.requested === true || !taskCanStart(task, this.catalog, null) : task.requested !== true)) {
        throw new Error(tr('Nie można zmienić kamery przy obecnym stanie zadania.', 'Camera task cannot be changed in its current state.'));
      }
      const result = await request(`/api/logic/feature/${this.taskName}`, {
        method: 'POST', body: { enabled, options: this.options }, timeout: 20000
      });
      if (result.data?.ok !== true) throw new Error(result.data?.result?.error || result.data?.error || 'camera_request_failed');
      if (enabled) this.onStarted(); else this.onStopped();
      text('operator-message', enabled
        ? tr('Kamera uruchomiona. Podgląd czeka na świeżą klatkę.', 'Camera started. Preview is waiting for a fresh frame.')
        : tr('Zadanie kamery zakończone. Inne aktywne zadania mogą nadal korzystać z kamery.', 'Camera task ended. Other active tasks may still use the camera.'));
      await this.load(true);
    } catch (error) { this.catalog = null; showError(error); }
    finally { this.busy = false; this.render(); this.poller.refresh(); }
  }
  render() {
    const task = this.task(), known = this.known();
    if (this.start) this.start.disabled = this.busy || !known || task.requested === true || !taskCanStart(task, this.catalog, null);
    if (this.stop) this.stop.disabled = this.busy || !known || task.requested !== true;
    for (const toggle of this.toggles) {
      const enabled = known && task.requested === true;
      toggle.disabled = this.busy || !known || (!enabled && !taskCanStart(task, this.catalog, null));
      toggle.setAttribute('aria-pressed', String(enabled));
      toggle.textContent = `${this.label ? this.label + ': ' : ''}${powerLabel(known ? enabled : null)}`;
      toggle.title = enabled ? tr('Wyłącz kamerę', 'Turn camera off') : tr('Włącz kamerę', 'Turn camera on');
    }
    let label = !known ? tr('Kamera: Nieznany — brak odczytu', 'Camera: Unknown — state unavailable')
      : task.requested === true ? task.ready === true ? tr('Kamera: ON', 'Camera: ON') : tr('Kamera uruchamiana — oczekiwanie na gotowość', 'Camera starting — waiting for readiness')
      : tr('Podgląd: OFF', 'Preview: OFF');
    const activity = this.catalog?.resource_states?.camera;
    if (known && activity) label = tr('Kamera: ', 'Camera: ') + powerLabel(
      !activity.error && activity.stale !== true && activity.offline !== true ? activity.on : null)
      + (task.requested === true && task.ready !== true ? ' · ' + tr('Uruchamianie', 'Starting') : '');
    if (known && task.error) label = tr('Błąd kamery: ', 'Camera error: ') + task.error;
    if (known && task.start_available === false) label += ' · ' + (task.start_unavailable_reason || tr('Uruchomienie niedostępne', 'Start unavailable'));
    const others = known ? this.catalog.features.filter(row => row.name !== this.taskName && row.requested === true && row.resources?.includes('camera')) : [];
    if (others.length) label += ' · ' + tr('Z kamery korzystają też: ', 'Camera also used by: ') + others.map(row => tr(row.title || row.name, row.title_en || row.name)).join(', ');
    if (known && activity?.service_running === true && task.requested !== true)
      label += ' · ' + tr('Proces kamery nadal działa', 'Camera process still running');
    if (known && activity?.service_running === true && activity.data_fresh !== true)
      label += ' · ' + tr('Brak świeżych klatek', 'No fresh frames');
    for (const id of this.statusIds) text(id, this.busy ? tr('Zmiana stanu kamery…', 'Changing camera state…') : label);
  }
}
