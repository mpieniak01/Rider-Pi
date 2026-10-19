import { requestId } from './request-id.js';
import { catalogKnown, taskCanStart, fresh } from './model.js';
import { request, poll } from './transport.js';
import { text, tr, showError, powerLabel } from './ui.js';

const CAMERA_TASK = 's2_camera_preview';
// Explicit operator clicks only. Page entry and polling remain read-only.
export class CameraPower {
  constructor({ onStarted = () => {}, onStopped = () => {}, taskName = CAMERA_TASK, options = {},
    toggleIds = ['camera-toggle'], statusIds = ['camera-power-state'], label = 'Kamera',
    startId = 'camera-start', stopId = 'camera-stop', pipelineProcessing = false } = {}) {
    this.pipelineProcessing = pipelineProcessing;
    this.taskName = taskName; this.options = options; this.statusIds = statusIds; this.label = label;
    this.catalog = null; this.pipeline = undefined; this.busy = false; this.onStarted = onStarted; this.onStopped = onStopped;
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
    this.catalog = (await request('/api/logic/catalog', { force })).data;
    if ([CAMERA_TASK, 's7_obstacle_module'].includes(this.taskName)) {
      try {
        const value = (await request('/api/resource/camera/pipeline', { force })).data;
        this.pipeline = value?.contract_id === 'rider.camera_pipeline' && value.contract_version === 1 ? value : undefined;
      } catch (error) {
        if (error.status !== 404 && error.data?.meta?.contract_id !== 'rider.resources') throw error;
        this.pipeline = undefined;
      }
    }
    this.render();
  }
  task() {
    const task = this.catalog?.features?.find(task => task.name === this.taskName);
    if (!task || !this.pipeline || this.taskName === 's7_obstacle_module' && !this.pipelineProcessing) return task;
    const running = ['active', 'waiting_frame', 'starting'].includes(this.pipeline.state);
    const requested = running && (this.taskName === CAMERA_TASK || this.pipeline.profile.analysis_location === 'local');
    return { ...task, requested, ready: requested && this.pipeline.state === 'active' };
  }
  canStart(task) {
    if (!this.pipeline) return taskCanStart(task, this.catalog, null);
    return !['starting', 'stopping', 'waiting_frame'].includes(this.pipeline.state)
      && (this.taskName !== 's7_obstacle_module' || this.pipeline.capabilities.analysis_locations.includes('local'));
  }
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
      if (!this.known() || (enabled ? task.requested === true || !this.canStart(task) : task.requested !== true)) {
        throw new Error(tr('Nie można zmienić kamery przy obecnym stanie zadania.', 'Camera task cannot be changed in its current state.'));
      }
      if (this.pipeline) {
        let current = this.pipeline;
        if (enabled && this.taskName === 's7_obstacle_module' && current.profile.analysis_location !== 'local') {
          current = (await request('/api/resource/camera/pipeline', { method: 'POST', timeout: 20000, body: {
            contract_version: 1, request_id: requestId('camera'), expected_revision: current.revision, action: 'configure',
            profile: { ...current.profile, analysis_location: 'local', local_engine: 'canny' },
          } })).data;
          if (current?.ok !== true) throw new Error(current?.error || 'camera_request_failed');
        }
        const taskOnly = this.taskName === 's7_obstacle_module' && !this.pipelineProcessing;
        const result = taskOnly ? await request('/api/logic/feature/' + this.taskName, {
          method: 'POST', body: { enabled, options: this.options }, timeout: 20000,
        }) : await request('/api/resource/camera/pipeline', { method: 'POST', timeout: 20000, body: {
          contract_version: 1, request_id: requestId('camera'), expected_revision: current.revision,
          action: enabled ? 'start' : 'stop',
        } });
        if (result.data?.ok !== true) throw new Error(result.data?.error || 'camera_request_failed');
        this.pipeline = taskOnly ? current : result.data;
      } else {
        const result = await request('/api/logic/feature/' + this.taskName, {
          method: 'POST', body: { enabled, options: this.options }, timeout: 20000
        });
        if (result.data?.ok !== true) throw new Error(result.data?.result?.error || result.data?.error || 'camera_request_failed');
      }
      if (enabled) this.onStarted(); else this.onStopped();
      text('operator-message', enabled
        ? tr('Kamera uruchomiona. Podgląd czeka na świeżą klatkę.', 'Camera started. Preview is waiting for a fresh frame.')
        : tr('Zadanie kamery zakończone. Inne aktywne zadania mogą nadal korzystać z kamery.', 'Camera task ended. Other active tasks may still use the camera.'));
      await this.load(true);
    } catch (error) { this.catalog = null; showError(error); }
    finally { this.busy = false; this.render(); void this.poller.refresh(); }
  }
  render() {
    const task = this.task(), known = this.known();
    if (this.start) this.start.disabled = this.busy || !known || task.requested === true || !this.canStart(task);
    if (this.stop) this.stop.disabled = this.busy || !known || task.requested !== true;
    for (const toggle of this.toggles) {
      const enabled = known && task.requested === true;
      toggle.disabled = this.busy || !known || (!enabled && !this.canStart(task));
      toggle.setAttribute('aria-pressed', String(enabled));
      toggle.textContent = `${this.label ? this.label + ': ' : ''}${powerLabel(known ? enabled : null)}`;
      toggle.title = enabled ? tr('Wyłącz kamerę', 'Turn camera off') : tr('Włącz kamerę', 'Turn camera on');
    }
    let label = !known ? tr('Kamera: Nieznany — brak odczytu', 'Camera: Unknown — state unavailable')
      : task.requested === true ? task.ready === true ? tr('Kamera: ON', 'Camera: ON') : tr('Kamera uruchamiana — oczekiwanie na gotowość', 'Camera starting — waiting for readiness')
      : tr('Podgląd: OFF', 'Preview: OFF');
    const activity = this.catalog?.resource_states?.camera;
    if (known && activity && this.taskName === CAMERA_TASK) label = tr('Kamera: ', 'Camera: ') + powerLabel(
      !activity.error && activity.stale !== true && activity.offline !== true ? activity.on : null)
      + (task.requested === true && task.ready !== true ? ' · ' + tr('Uruchamianie', 'Starting') : '');
    if (known && this.taskName !== CAMERA_TASK)
      label = tr('Przetwarzanie: ', 'Processing: ') + powerLabel(task.requested === true)
        + (task.requested === true && task.ready !== true ? ' · ' + tr('Uruchamianie', 'Starting') : '');
    if (known && task.error) label = tr('Błąd kamery: ', 'Camera error: ') + task.error;
    if (known && task.start_available === false) label += ' · ' + (task.start_unavailable_reason || tr('Uruchomienie niedostępne', 'Start unavailable'));
    const others = known ? this.catalog.features.filter(row => row.name !== this.taskName && row.requested === true && row.resources?.includes('camera')) : [];
    if (others.length) label += ' · ' + tr('Z kamery korzystają też: ', 'Camera also used by: ') + others.map(row => tr(row.title || row.name, row.title_en || row.name)).join(', ');
    if (known && activity?.service_running === true && task.requested !== true && this.taskName === CAMERA_TASK)
      label += ' · ' + tr('Proces kamery nadal działa', 'Camera process still running');
    if (known && activity?.service_running === true && activity.data_fresh !== true && this.taskName === CAMERA_TASK)
      label += ' · ' + tr('Brak świeżych klatek', 'No fresh frames');
    for (const id of this.statusIds) text(id, this.busy ? tr('Zmiana stanu kamery…', 'Changing camera state…') : label);
  }
}
