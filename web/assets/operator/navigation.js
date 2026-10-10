import { ageOf, fresh, safetyKnown, gridPoint, nowSeconds, presentationReady, navigationObservation } from './model.js';
import { request, poll } from './transport.js';
import { el, text, tr, showError } from './ui.js';
export class Navigation {
  constructor(safety) {
    this.safety = safety; this.map = null; this.pose = null; this.path = null; this.busy = false; this.drawKey = null; this.history = [];
    this.canvas = document.getElementById('map-canvas');
    for (const action of ['start', 'return_home']) document.getElementById(`nav-${action}`)?.addEventListener('click', () => this.command(action).catch(showError));
    document.getElementById('nav-stop')?.addEventListener('click', () => safety.stop());
    document.getElementById('nav-config-form')?.addEventListener('submit', event => { event.preventDefault(); this.config().catch(showError); });
    this.poller = poll(async () => {
      const data = (await request('/api/navigator/status')).data;
      this.observeSnapshot(data.navigation, data);
      const status = data.navigator || data.status || data;
      this.observeRequest(status, data);
      text('nav-status', `${this.statusCurrent(status, data) ? status.state || status.mode || 'unknown' : 'unknown / stale'} · ${tr('wiek', 'age')}: ${ageOf(status)?.toFixed(1) ?? '—'} s`);
      this.render();
    }, { interval: 2000, onError: error => {
      for (const name of ['map', 'pose', 'path']) this[name] = { ...this[name], offline: true, error: error.message };
      text('nav-status', 'unknown'); this.render(); showError(error);
    } });
    window.addEventListener('resize', () => { this.drawKey = null; this.draw(); });
  }
  observeSnapshot(snapshot, outer = {}) {
    for (const name of ['map', 'pose', 'path']) {
      const child = snapshot?.[name];
      const row = child && typeof child === 'object' && !Array.isArray(child) ? { ...child } : null;
      // A cached envelope can fail independently of its original observations.
      // Propagate only failures; preserve each child's source and source time.
      if (row) {
        for (const parent of [snapshot, outer]) {
          for (const key of ['stale', 'offline']) if (parent[key] === true) row[key] = true;
          for (const key of ['error', 'data_error']) if (parent[key]) row[key] = parent[key];
        }
        // Outer task readiness is distinct from cached measurement readiness.
        for (const key of ['data_ready', 'navigation_ready']) if (snapshot[key] === false) row[key] = false;
        const quality = typeof snapshot.quality === 'string' ? snapshot.quality.toLowerCase() : snapshot.quality;
        if (quality === null || ['unknown', 'unavailable', 'invalid', 'error', 'failed'].includes(quality)) row.quality = snapshot.quality;
      }
      this[name] = navigationObservation(row, this[name]);
    }
  }
  async command(action) {
    if (this.busy || !this.safety.can('navigation') || !this.safety.can('navigation', 'turn')) return;
    const envelope = this.safety.envelope('move', {}, 'navigation');
    const body = { ...envelope, strategy: document.getElementById('nav-strategy').value }; delete body.action;
    const entry = { action, request_id: envelope.request_id, generation: envelope.generation, ts: envelope.ts, status: 'pending' };
    this.history.unshift(entry); this.history = this.history.slice(0, 20);
    this.busy = true; this.render();
    text('nav-request', `${action}: pending`);
    try {
      const { data, status } = await request(`/api/navigator/${action}`, { method: 'POST', body });
      text('nav-request', `${action}: ${status === 202 || data.pending ? 'pending' : 'response_received'} · ${data.request_id || envelope.request_id}`);
    } catch (error) { entry.status = error.status ? 'rejected' : 'unknown'; text('nav-request', `${action}: ${entry.status}`); showError(error); }
    finally { this.busy = false; this.render(); this.poller.refresh(); }
  }
  async config() {
    if (!safetyKnown(this.safety.state) || this.safety.state.state !== 'DISARMED' || this.busy) return;
    const numbers = ['nav-speed', 'nav-turn'].map(id => { const value = document.getElementById(id).value.trim(); return value ? Number(value) : NaN; });
    if (numbers.some(value => !Number.isFinite(value) || value < 0 || value > 1)) return showError(new Error(tr('Prędkości muszą być liczbami w zakresie 0–1.', 'Speeds must be numbers in range 0–1.')));
    this.busy = true; this.render();
    try {
      const result = await request('/api/navigator/config', { method: 'POST', body: {
        strategy: document.getElementById('nav-strategy').value,
        fwd_speed: numbers[0], turn_speed: numbers[1] } });
      text('nav-request', `${tr('Konfiguracja', 'Configuration')}: ${result.status === 202 || result.data.pending ? 'pending' : 'response_received'}`);
    } catch (error) { showError(error); }
    finally { this.busy = false; this.render(); }
  }
  event(event) {
    let data = event.data;
    try { if (typeof data === 'string') data = JSON.parse(data); } catch { data = null; }
    // Invalid/unknown observations expire the presentation instead of leaving
    // the previous geometry looking healthy. Source time is never restamped.
    for (const [topic, name] of [['mapper.map.data', 'map'], ['robot.pose', 'pose'], ['navigator.path', 'path']]) {
      if (event.topic === topic) this[name] = navigationObservation(data, this[name]);
    }
    if (!data || typeof data !== 'object') { this.render(); return; }
    const timestamp = Object.hasOwn(data, 'observed_at') ? data.observed_at : data.ts;
    if (event.topic === 'navigator.state') this.observeRequest(data);
    if (event.topic?.startsWith('navigator.')) text('nav-event', `${event.topic} · ${data.state || data.status || data.reason || 'received'} · ${timestamp ?? '—'}`);
    this.render();
  }
  statusCurrent(status, outer = {}) {
    return fresh(status) && ![status, outer].some(row => row?.stale === true || row?.offline === true || row?.error || row?.data_error);
  }
  observeRequest(status, outer = {}) {
    if (!this.statusCurrent(status, outer) || typeof status.active !== 'boolean' || typeof status.state !== 'string') return;
    const entry = this.history.find(row => row.request_id === status.request_id && row.generation === status.generation && status.observed_at >= row.ts);
    if (!entry) return;
    entry.status = 'task_observed'; entry.state = status.state; entry.active = status.active;
    text('nav-request', `${entry.action}: ${tr('stan zadania potwierdzony', 'task state observed')} · ${status.state} · ${entry.request_id}`);
  }
  render() {
    const allowed = this.safety.can('navigation') && this.safety.can('navigation', 'turn');
    for (const action of ['start', 'return_home']) { const button = document.getElementById(`nav-${action}`); if (button) button.disabled = !allowed || this.busy; }
    const config = document.getElementById('nav-config'); if (config) config.disabled = !safetyKnown(this.safety.state) || this.safety.state.state !== 'DISARMED' || this.busy;
    text('map-age', `${tr('Mapa', 'Map')}: ${ageOf(this.map)?.toFixed(1) ?? '—'} s · ${this.map?.quality ?? 'unknown'}${presentationReady(this.map, 10) ? '' : ' · unavailable / stale'}`);
    text('pose-age', `${tr('Pozycja', 'Pose')}: ${ageOf(this.pose)?.toFixed(1) ?? '—'} s · ${this.pose?.quality ?? 'unknown'}${presentationReady(this.pose) ? '' : ' · unavailable / stale'}`);
    text('path-age', `${tr('Plan trasy', 'Planned path')}: ${ageOf(this.path)?.toFixed(1) ?? '—'} s · ${this.path?.quality ?? 'unknown'}${presentationReady(this.path) ? '' : ' · unavailable / stale'}`);
    for (const entry of this.history) if (entry.status === 'pending' && nowSeconds() - entry.ts > 8) entry.status = 'unknown';
    document.getElementById('nav-request-history')?.replaceChildren(...this.history.map(entry => el('li', '', `${entry.action} · ${entry.status === 'task_observed' ? tr('stan zadania potwierdzony', 'task state observed') : entry.status} · ${entry.state || '—'} · ${entry.request_id}`)));
    this.draw();
  }
  draw() {
    if (!this.canvas) return;
    const displayWidth = Math.min(1000, this.canvas.clientWidth || 600);
    const key = JSON.stringify([displayWidth, ...['map', 'pose', 'path'].map(name => {
      const row = this[name];
      return [row?.observed_at, presentationReady(row, name === 'map' ? 10 : 3),
        row?.quality, row?.stale, row?.offline, row?.error, row?.data_ready, row?.navigation_ready, row?.data_error];
    })]);
    if (key === this.drawKey) return;
    this.drawKey = key;
    const ctx = this.canvas.getContext('2d');
    const width = this.map?.width_cells, height = this.map?.height_cells;
    this.canvas.width = displayWidth; this.canvas.height = Math.round(this.canvas.width * .6);
    ctx.fillStyle = '#192430'; ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0 || width * height > 65536) return;
    const grid = this.map.grid;
    if (!Array.isArray(grid) || grid.length > 65536) return;
    if (Array.isArray(grid[0]) && (grid.length !== height || grid.some(row => !Array.isArray(row) || row.length !== width))) return;
    const data = grid.flat();
    if (data.length !== width * height) return;
    if (data.some(value => !Number.isFinite(value))) return;
    const scale = Math.min(this.canvas.width / width, this.canvas.height / height);
    const offsetX = (this.canvas.width - width * scale) / 2, offsetY = (this.canvas.height - height * scale) / 2;
    ctx.save(); ctx.translate(offsetX, offsetY); ctx.globalAlpha = presentationReady(this.map, 10) ? 1 : .45;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const cell = data[y * width + x]; ctx.fillStyle = cell === 255 ? '#f77272' : cell === 0 ? '#708793' : '#263442'; ctx.fillRect(x * scale, y * scale, scale, scale);
    }
    const waypoints = Array.isArray(this.path?.path) && this.path.path.length <= 2000
      ? this.path.path.map(point => gridPoint(this.map, point)).filter(Boolean) : [];
    ctx.globalAlpha = presentationReady(this.path) ? 1 : .35; ctx.strokeStyle = '#7dadff'; ctx.lineWidth = 2;
    if (waypoints.length > 1) {
      ctx.beginPath(); ctx.moveTo(waypoints[0][0] * scale, waypoints[0][1] * scale);
      for (const [x, y] of waypoints.slice(1)) ctx.lineTo(x * scale, y * scale);
      ctx.stroke();
    }
    const target = gridPoint(this.map, this.path?.target);
    if (target) { ctx.fillStyle = '#ffce78'; ctx.beginPath(); ctx.arc(target[0] * scale, target[1] * scale, 5, 0, Math.PI * 2); ctx.fill(); }
    const pose = gridPoint(this.map, this.pose);
    if (pose && Number.isFinite(this.pose.theta)) {
      ctx.globalAlpha = presentationReady(this.pose) ? 1 : .35; ctx.translate(pose[0] * scale, pose[1] * scale); ctx.rotate(this.pose.theta);
      ctx.fillStyle = '#4ae0d2'; ctx.beginPath(); ctx.arc(0, 0, Math.max(3, scale * .6), 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.max(7, scale), 0); ctx.stroke();
    }
    ctx.restore();
  }
}
