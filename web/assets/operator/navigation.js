import { ageOf, fresh, safetyKnown, gridPoint, nowSeconds, presentationReady, navigationObservation,
  planningPresentationReady, passivePlanObservation, sameNavigationFrame, passivePlanCurrent } from './model.js';
import { request, poll } from './transport.js';
import { el, text, tr, showError } from './ui.js';
function inheritFailures(row,parent,allowPlanningRefusal=false) {
  for (const key of ['stale', 'offline']) if (parent[key] === true) row[key] = true;
  for (const key of ['error', 'data_error']) {
    if (!parent[key]) continue;
    if (allowPlanningRefusal && key === 'data_error' && parent.planning_only === true
      && parent.data_error === 'navigation_traversal_unverified') continue;
    row[key] = parent[key];
  }
}
function snapshotObservation(child,snapshot,outer) {
  const row = child && typeof child === 'object' && !Array.isArray(child) ? { ...child } : null;
  if (!row) return null;
  // A cached envelope can fail independently; retain child source timestamps.
  inheritFailures(row,snapshot,snapshot===outer);
  inheritFailures(row,outer,true);
  // Outer task readiness is distinct from cached measurement readiness.
  for (const key of ['data_ready', 'navigation_ready']) if (snapshot[key] === false) row[key] = false;
  const quality = typeof snapshot.quality === 'string' ? snapshot.quality.toLowerCase() : snapshot.quality;
  if (quality === null || ['unknown', 'unavailable', 'invalid', 'error', 'failed'].includes(quality)) row.quality = snapshot.quality;
  return row;
}
function mapGrid(map) {
  const width = map?.width_cells, height = map?.height_cells;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0 || width * height > 65536) return null;
  const grid = map.grid;
  if (!Array.isArray(grid) || grid.length > 65536) return null;
  if (Array.isArray(grid[0]) && (grid.length !== height || grid.some(row => !Array.isArray(row) || row.length !== width))) return null;
  const data = grid.flat();
  if (data.length !== width * height || data.some(value => !Number.isFinite(value))) return null;
  return {width,height,data};
}
function mapCellColor(cell) {
  if (cell === 255) return '#f77272';
  return cell === 0 ? '#708793' : '#263442';
}
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
      this.observeStatus(status, data);
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
      const row = snapshotObservation(snapshot?.[name],snapshot,outer);
      this[name] = navigationObservation(row, this[name]);
    }
  }
  async command(action) {
    // A point plan has no physical corridor proof. The retained legacy route
    // requires motion consent; it is not a DISARMED planning interface.
    text('nav-request', `${action}: ${action === 'return_home' ? 'passive_plan_request_unavailable' : 'navigation_traversal_unverified'}`);
    this.render();
  }
  async config() {
    if (!safetyKnown(this.safety.state) || this.safety.state.state !== 'DISARMED' || this.busy) return;
    const numbers = ['nav-speed', 'nav-turn'].map(id => { const value = document.getElementById(id).value.trim(); return value ? Number(value) : Number.NaN; });
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
    if (event.topic === 'navigator.state') { this.observeStatus(data); this.observeRequest(data); }
    if (event.topic?.startsWith('navigator.')) text('nav-event', `${event.topic} · ${data.state || data.status || data.reason || 'received'} · ${timestamp ?? '—'}`);
    this.render();
  }
  statusCurrent(status, outer = {}) {
    // A fresh passive domain refusal is useful task state. An outer proxy
    // failure or an explicit transport error cannot confirm any observation.
    return fresh(status) && ![status, outer].some(row => row?.stale === true || row?.offline === true || row?.error)
      && (!status.data_error || (status.planning_only === true && typeof status.data_error === 'string'))
      && (outer === status || !outer.data_error);
  }
  observeStatus(status, outer = {}) {
    this.status = status;
    if (!status || typeof status !== 'object') return;
    if (status.planning_only === true || Object.hasOwn(status, 'planned_path')) {
      const row = { ...status };
      if (outer !== status) {
        inheritFailures(row,outer);
      }
      this.path = passivePlanObservation(row, this.path);
    }
  }
  observeRequest(status, outer = {}) {
    if (!this.statusCurrent(status, outer) || typeof status.active !== 'boolean' || typeof status.state !== 'string') return;
    const entry = this.history.find(row => row.request_id === status.request_id && row.generation === status.generation && status.observed_at >= row.ts);
    if (!entry) return;
    entry.status = 'task_observed'; entry.state = status.state; entry.active = status.active; entry.error = status.data_error;
    text('nav-request', `${entry.action}: ${tr('stan zadania potwierdzony', 'task state observed')} · ${status.state} · ${status.data_error || '—'} · ${entry.request_id}`);
  }
  renderControls() {
    for (const action of ['start', 'return_home']) { const button = document.getElementById(`nav-${action}`); if (button) button.disabled = true; }
    const config = document.getElementById('nav-config'); if (config) config.disabled = !safetyKnown(this.safety.state) || this.safety.state.state !== 'DISARMED' || this.busy;
  }
  renderAges(planReady) {
    let mapState=' · unavailable / stale';
    if(planningPresentationReady(this.map,3))mapState=tr(' · tylko planowanie',' · planning only');
    else if(presentationReady(this.map,10))mapState='';
    text('map-age', `${tr('Mapa', 'Map')}: ${ageOf(this.map)?.toFixed(1) ?? '—'} s · ${this.map?.quality ?? 'unknown'}${mapState}`);
    text('pose-age', `${tr('Pozycja', 'Pose')}: ${ageOf(this.pose)?.toFixed(1) ?? '—'} s · ${this.pose?.quality ?? 'unknown'}${presentationReady(this.pose, .5) ? '' : ' · unavailable / stale'}`);
    text('path-age', `${tr('Pasywny plan punktowy', 'Passive point plan')}: ${ageOf(this.path)?.toFixed(1) ?? '—'} s${planReady ? '' : ' · unavailable / stale'} · ${tr('fizycznie niezweryfikowany', 'physically unverified')}`);
    if (this.path?.path_truncated === true) text('path-age', `${document.getElementById('path-age')?.textContent || ''} · ${tr('fragment', 'prefix')}: ${this.path.path.length}/${this.path.path_length}`);
    text('nav-reason', `${tr('Ruch autonomiczny niedostępny', 'Autonomous motion unavailable')}: ${this.status?.data_error || 'navigation_traversal_unverified'} · passive_plan_request_unavailable`);
  }
  renderGoal(planReady) {
    const target = this.path?.target;
    let label=tr('HOME / cel niepotwierdzony w bieżącej ramie','HOME / target unconfirmed in current frame');
    if(target && sameNavigationFrame(this.pose,this.path) && sameNavigationFrame(this.map,this.path)){
      const status=planReady?tr('plan tylko do odczytu','read-only plan'):tr('stary plan','stale plan');
      label=`HOME: (${target[0]}, ${target[1]}) · ${this.path.reference_id} · ${status}`;
    }
    text('nav-goal',label);
  }
  renderHistory() {
    for (const entry of this.history) if (entry.status === 'pending' && nowSeconds() - entry.ts > 8) entry.status = 'unknown';
    document.getElementById('nav-request-history')?.replaceChildren(...this.history.map(entry => el('li', '', `${entry.action} · ${entry.status === 'task_observed' ? tr('stan zadania potwierdzony', 'task state observed') : entry.status} · ${entry.state || '—'} · ${entry.request_id}`)));
  }
  render() {
    this.renderControls();
    const planReady = passivePlanCurrent(this.path, this.map, this.pose);
    this.renderAges(planReady);this.renderGoal(planReady);this.renderHistory();this.draw();
  }
  draw() {
    if (!this.canvas) return;
    const displayWidth = Math.min(1000, this.canvas.clientWidth || 600);
    const key = JSON.stringify([displayWidth, passivePlanCurrent(this.path, this.map, this.pose), ...['map', 'pose', 'path'].map(name => {
      const row = this[name];
      return [row?.observed_at, presentationReady(row, name === 'map' ? 10 : 3),
        planningPresentationReady(row), row?.calibration_id, row?.reference_id, row?.home,
        row?.quality, row?.stale, row?.offline, row?.error, row?.data_ready, row?.navigation_ready, row?.data_error];
    })]);
    if (key === this.drawKey) return;
    this.drawKey = key;
    const ctx = this.canvas.getContext('2d');
    this.canvas.width = displayWidth; this.canvas.height = Math.round(this.canvas.width * .6);
    ctx.fillStyle = '#192430'; ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    const grid = mapGrid(this.map);if (!grid) return;
    const {width,height} = grid;
    const scale = Math.min(this.canvas.width / width, this.canvas.height / height);
    const offsetX = (this.canvas.width - width * scale) / 2, offsetY = (this.canvas.height - height * scale) / 2;
    ctx.save(); ctx.translate(offsetX, offsetY); ctx.globalAlpha = planningPresentationReady(this.map, 3) || presentationReady(this.map, 10) ? 1 : .45;
    this.drawGrid(ctx,grid,scale);
    this.drawPath(ctx,scale);this.drawPose(ctx,scale);
    ctx.restore();
  }
  drawGrid(ctx,{width,height,data},scale) {
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const cell = data[y * width + x]; ctx.fillStyle = mapCellColor(cell); ctx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
  drawPath(ctx,scale) {
    const pathFrame = sameNavigationFrame(this.map, this.path) && sameNavigationFrame(this.pose, this.path);
    const waypoints = pathFrame && Array.isArray(this.path?.path) && this.path.path.length <= 2000
      ? this.path.path.map(point => gridPoint(this.map, point)).filter(Boolean) : [];
    ctx.globalAlpha = passivePlanCurrent(this.path, this.map, this.pose) ? 1 : .35; ctx.strokeStyle = '#7dadff'; ctx.lineWidth = 2;
    if (waypoints.length > 1) {
      ctx.beginPath(); ctx.moveTo(waypoints[0][0] * scale, waypoints[0][1] * scale);
      for (const [x, y] of waypoints.slice(1)) ctx.lineTo(x * scale, y * scale);
      ctx.stroke();
    }
    const target = pathFrame ? gridPoint(this.map, this.path?.target) : null;
    if (target) { ctx.fillStyle = '#ffce78'; ctx.beginPath(); ctx.arc(target[0] * scale, target[1] * scale, 5, 0, Math.PI * 2); ctx.fill(); }
  }
  drawPose(ctx,scale) {
    const pose = sameNavigationFrame(this.map, this.pose) ? gridPoint(this.map, this.pose) : null;
    if (pose && Number.isFinite(this.pose.theta)) {
      ctx.globalAlpha = presentationReady(this.pose, .5) ? 1 : .35; ctx.translate(pose[0] * scale, pose[1] * scale); ctx.rotate(this.pose.theta);
      ctx.fillStyle = '#4ae0d2'; ctx.beginPath(); ctx.arc(0, 0, Math.max(3, scale * .6), 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.max(7, scale), 0); ctx.stroke();
    }
  }
}
