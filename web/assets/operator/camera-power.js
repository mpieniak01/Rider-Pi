import { catalogKnown, taskCanStart, fresh } from './model.js';
import { request, poll } from './transport.js';
import { text, tr, showError } from './ui.js';

const CAMERA_TASK = 's2_camera_preview';
// Explicit operator clicks only. Page entry and polling remain read-only.
export class CameraPower {
  constructor({ onStarted = () => {}, onStopped = () => {} } = {}) {
    this.catalog = null; this.busy = false; this.onStarted = onStarted; this.onStopped = onStopped;
    this.start = document.getElementById('camera-start'); this.stop = document.getElementById('camera-stop');
    this.toggle = document.getElementById('camera-toggle');
    this.toggle?.addEventListener('click', () => { if (this.known()) return this.change(this.task().requested !== true); });
    this.start?.addEventListener('click', () => this.change(true));
    this.stop?.addEventListener('click', () => this.change(false));
    this.poller = poll(() => this.load(), { interval: 5000, onError: error => {
      this.catalog = null; this.render(); showError(error);
    } });
    this.expiry = setInterval(() => this.render(), 1000);
    window.addEventListener('dashboard:langchange', () => this.render());
    window.addEventListener('pagehide', () => { this.poller.stop(); clearInterval(this.expiry); });
    this.render();
  }
  async load() {
    this.catalog = (await request('/api/logic/catalog')).data; this.render();
  }
  task() { return this.catalog?.features?.find(task => task.name === CAMERA_TASK); }
  known() {
    const task = this.task();
    return catalogKnown(this.catalog) && task?.can_move === false && fresh(task, 10);
  }
  async change(enabled) {
    if (this.busy) return;
    this.busy = true; this.render();
    try {
      // Recheck the task immediately before an explicit start/stop.
      await this.load();
      const task = this.task();
      if (!this.known() || (enabled ? task.requested === true || !taskCanStart(task, this.catalog, null) : task.requested !== true)) {
        throw new Error(tr('Nie można zmienić kamery przy obecnym stanie zadania.', 'Camera task cannot be changed in its current state.'));
      }
      const result = await request(`/api/logic/feature/${CAMERA_TASK}`, {
        method: 'POST', body: { enabled, options: {} }, timeout: 20000
      });
      if (result.data?.ok !== true) throw new Error(result.data?.result?.error || result.data?.error || 'camera_request_failed');
      if (enabled) this.onStarted(); else this.onStopped();
      text('operator-message', enabled
        ? tr('Kamera uruchomiona. Podgląd czeka na świeżą klatkę.', 'Camera started. Preview is waiting for a fresh frame.')
        : tr('Zadanie kamery zakończone. Inne aktywne zadania mogą nadal korzystać z kamery.', 'Camera task ended. Other active tasks may still use the camera.'));
      await this.load();
    } catch (error) { this.catalog = null; showError(error); }
    finally { this.busy = false; this.render(); this.poller.refresh(); }
  }
  render() {
    const task = this.task(), known = this.known();
    if (this.start) this.start.disabled = this.busy || !known || task.requested === true || !taskCanStart(task, this.catalog, null);
    if (this.stop) this.stop.disabled = this.busy || !known || task.requested !== true;
    if (this.toggle) {
      const enabled = known && task.requested === true;
      this.toggle.disabled = this.busy || !known || (!enabled && !taskCanStart(task, this.catalog, null));
      this.toggle.setAttribute('aria-pressed', String(enabled));
      this.toggle.textContent = `Kamera: ${enabled ? 'ON' : 'OFF'}`;
      this.toggle.title = enabled ? tr('Wyłącz kamerę', 'Turn camera off') : tr('Włącz kamerę', 'Turn camera on');
    }
    let label = !known ? tr('Stan kamery nieznany — odczytywanie stanu', 'Camera state unknown — reading status')
      : task.requested === true ? task.ready === true ? tr('Kamera włączona', 'Camera on') : tr('Kamera uruchamiana — oczekiwanie na gotowość', 'Camera starting — waiting for readiness')
      : tr('Podgląd kamery wyłączony', 'Camera preview off');
    if (known && task.error) label = tr('Błąd kamery: ', 'Camera error: ') + task.error;
    if (known && task.start_available === false) label += ' · ' + (task.start_unavailable_reason || tr('Uruchomienie niedostępne', 'Start unavailable'));
    const others = known ? this.catalog.features.filter(row => row.name !== CAMERA_TASK && row.requested === true && row.resources?.includes('camera')) : [];
    if (others.length) label += ' · ' + tr('Z kamery korzystają też: ', 'Camera also used by: ') + others.map(row => tr(row.title || row.name, row.title_en || row.name)).join(', ');
    text('camera-power-state', this.busy ? tr('Zmiana stanu kamery…', 'Changing camera state…') : label);
  }
}
