import { request, poll } from './transport.js';
import { ageOf, fresh, presentationReady, cameraFrame, catalogKnown, nowSeconds } from './model.js';
import { el, text, tr, statusLabel, powerLabel } from './ui.js';
import { telemetryChannel } from './devices.js?v=extended-telemetry-1';
import { telemetrySummary, orientationSummary } from './overview-model.js';

const finite = value => typeof value === 'number' && Number.isFinite(value);
const fmt = (value, digits = 1) => finite(value) ? value.toFixed(digits) : '—';
const age = row => ageOf(row) === null ? '—' : `${ageOf(row).toFixed(1)} s`;
const frameAge = seconds => !finite(seconds) ? '—' : seconds >= 86400 ? `${Math.floor(seconds / 86400)} ${tr('dni', 'days')}` : seconds >= 3600 ? `${fmt(seconds / 3600)} h` : `${fmt(seconds)} s`;
const unknown = () => tr('brak / stary pomiar', 'missing / stale reading');
const BLANK = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"%3E%3Crect width="640" height="360" fill="%2306090d"/%3E%3C/svg%3E';

// Measurements remain read-only. The separate CameraPower control handles explicit camera clicks.
export class Overview {
  constructor(safety) {
    this.safety = safety;
    this.state = null; this.health = null; this.system = null; this.catalog = null;
    this.snap = null; this.obstacle = null; this.metrics = null;
    this.poller = poll(async () => {
      const results = await Promise.allSettled(['/healthz', '/api/logic/catalog']
        .map(path => request(path)));
      [this.health, this.catalog] = results.map(result => result.status === 'fulfilled' ? result.value.data : null);
      this.render();
    }, { profile: 'services' });
    this.systemPoller = poll(async () => {
      try { this.system = (await request('/sysinfo')).data; }
      catch { this.system = null; }
      this.renderSystem();
    }, { profile: 'system' });
    // One small telemetry read per second avoids expiring healthy 1 Hz samples
    // between refreshes. Filesystem/image metadata remains on its slower poll.
    this.telemetryPoller = poll(async () => {
      try { this.state = (await request('/state')).data; }
      catch { this.state = null; }
      this.renderTelemetry();
      window.dashboardFooter?.update({ state: this.state });
      if (this.state) window.dispatchEvent(new CustomEvent('dashboard:update', { detail: this.state }));
    }, { profile: 'telemetry' });
    this.visionPoller = poll(async () => {
      const results = await Promise.allSettled([request('/vision/snap-info?light=1'), request('/vision/obstacle')]);
      [this.snap, this.obstacle] = results.map(result => result.status === 'fulfilled' ? result.value.data : null);
      this.renderVision();
    }, { profile: 'vision' });
    poll(async () => {
      try { this.metrics = (await request('/api/app-metrics')).data; }
      catch { this.metrics = null; }
      this.renderMetrics();
    }, { profile: 'metrics' });
    this.expiry = setInterval(() => { if (!document.hidden) this.render(); }, 1000);
    window.addEventListener('dashboard:langchange', () => this.render());
    window.addEventListener('pagehide', () => clearInterval(this.expiry));
  }
  render() {
    this.renderSystem(); this.renderTelemetry(); this.renderHealth(); this.renderVision(); this.renderMetrics();
    window.dashboardFooter?.update({ state: this.state, snapInfo: this.snap });
    const target = document.getElementById('overview-tasks');
    if (target) target.replaceChildren(...(Array.isArray(this.catalog?.features) ? this.catalog.features : []).filter(task => task.requested).map(task =>
      el('li', '', `${tr(task.title || task.name, task.title_en || task.name)} · ${catalogKnown(this.catalog) && fresh(task, 10) ? statusLabel(task.state) : unknown()}${task.error ? ` · ${task.error}` : ''}`)));
    text('overview-task-status', catalogKnown(this.catalog) ? tr('Stan z katalogu v2', 'State from catalog v2') : unknown());
  }
  renderSystem() {
    const si = this.system, usable = presentationReady(si, 10);
    const value = key => usable ? si?.[key] : null;
    text('ci_host', si?.host || si?.hostname || location.hostname);
    text('ci_cpu', finite(value('cpu_pct')) ? `${fmt(value('cpu_pct'))}%` : '—');
    text('ci_load', ['load1', 'load5', 'load15'].map(key => fmt(value(key), 2)).join(' / '));
    text('ci_mem', finite(value('mem_total_mb')) && finite(value('mem_used_mb'))
      ? `${fmt(value('mem_used_mb'))} / ${fmt(value('mem_total_mb'))} MiB (${fmt(value('mem_pct'))}%)` : '—');
    text('ci_disk', finite(value('disk_total_gb')) && finite(value('disk_used_gb'))
      ? `${fmt(value('disk_used_gb'))} / ${fmt(value('disk_total_gb'))} GiB (${fmt(value('disk_pct'))}%)` : '—');
    text('ci_os', si?.os_release || si?.platform || '—');
    text('d_temp', finite(value('temp_c')) ? `${fmt(value('temp_c'))} °C` : '—');
    text('system-age', `${age(si)}${usable ? '' : ` · ${unknown()}`}`);
    this.drawHistory(usable ? si.hist_cpu : [], usable ? si.hist_mem : [],
      usable ? si.hist_cpu_peak : [], usable ? si.hist_ts : []);
    const cpu = document.getElementById('ci_cpu');
    if (cpu) cpu.title = usable && finite(si.cpu_peak_pct)
      ? tr('Szczyt w ostatniej sekundzie: ', 'Peak in the last second: ') + fmt(si.cpu_peak_pct) + '%' : '';
  }
  renderTelemetry() {
    const xgo = this.state?.devices?.xgo;
    const unavailable = this.state?.offline === true || this.state?.meta?.offline === true
      || this.state?.stale === true || this.state?.meta?.stale === true || Boolean(this.state?.error);
    const samples = Object.fromEntries(['roll', 'pitch', 'yaw', 'battery'].map(key => [key, telemetryChannel(xgo, key, unavailable)]));
    const values = ['roll', 'pitch', 'yaw'].map(key => samples[key].value);
    const battery = samples.battery.value;
    const imuReady = ['roll', 'pitch', 'yaw'].every(key => samples[key].ready);
    text('d_xgo_imu', imuReady ? tr('Świeży odczyt', 'Fresh reading') : values.some(finite) ? tr('Częściowy odczyt', 'Partial reading') : unknown());
    text('d_xgo_pose', orientationSummary(samples));
    const work = telemetryChannel(xgo, 'work_status', unavailable);
    text('d_xgo_work', work.ready ? (work.value === 1 ? tr('Normalny', 'Normal') : work.value === 0 ? tr('Przewrócony', 'Fallen') : unknown()) : unknown());
    const accel = ['accel_x', 'accel_y', 'accel_z'].map(key => telemetryChannel(xgo, key, unavailable));
    text('d_xgo_accel', accel.every(row => row.ready) ? accel.map(row => fmt(row.value, 2)).join(' / ') : unknown());
    text('d_xgo_batt', finite(battery) ? `${fmt(battery, 0)}%` : unknown());
    const group = telemetrySummary(samples, nowSeconds());
    text('xgo-age', group.complete ? `${fmt(group.age)} s` : tr('Częściowa / niedostępna', 'Partial / unavailable'));
    text('imu-yaw-raw', samples.yaw.ready ? `${fmt(samples.yaw.value, 2)} sdk_raw · ${age(samples.yaw)}` : unknown());
    text('ci_fw', xgo?.fw || this.health?.devices?.xgo?.fw || '—');
    const lcdParent = this.state?.devices?.lcd ? this.state : this.health;
    const lcd = lcdParent?.devices?.lcd;
    const lcdNow = nowSeconds();
    const lcdAge = ageOf({ observed_at: lcd?.power_observed_at }, lcdNow);
    const lcdFailure = [lcdParent, lcdParent?.meta, lcd].some(row => row?.offline === true
      || row?.stale === true || row?.simulated === true || Boolean(row?.error));
    const lcdConfirmed = !lcdFailure && lcd?.power_known === true && typeof lcd.on === 'boolean'
      && typeof lcd.source === 'string' && Boolean(lcd.source.trim()) && lcd.power_source === lcd.source
      && ['control_write_accepted', 'gpio_level_observed'].includes(lcd.confirmation) && lcdAge !== null && lcd.power_observed_at <= lcdNow;
    // LCD reports accepted control events, not periodic physical measurements.
    text('d_lcd', powerLabel(lcdConfirmed ? lcd.on : null));
    const lcdNode = document.getElementById('d_lcd');
    if (lcdNode) lcdNode.title = lcdConfirmed
      ? (lcd.confirmation === 'gpio_level_observed' ? tr('Odczyt podświetlenia LCD', 'LCD backlight reading')
        : tr('Ostatnie potwierdzone polecenie LCD', 'Last confirmed LCD command'))
      : tr('Nie można odczytać stanu LCD', 'LCD state unavailable');
  }
  renderHealth() {
    const h = this.health;
    text('h_status', !h ? tr('Brak połączenia z API', 'API unavailable') : h.status || (h.ok === true ? 'OK' : tr('Stan nieznany', 'State unknown')));
    const healthNode = document.getElementById('h_status');
    if (healthNode) healthNode.className = h?.status === 'ok' || h?.ok === true ? 'ok' : h ? 'bad' : 'muted';
    text('h_uptime', finite(h?.uptime_s ?? h?.uptime) ? `${fmt(h.uptime_s ?? h.uptime, 0)} s` : '—');
    text('h_msg', finite(h?.bus?.last_msg_age_s) ? `${fmt(h.bus.last_msg_age_s)} s` : '—');
    text('h_hb', finite(h?.bus?.last_heartbeat_age_s) ? `${fmt(h.bus.last_heartbeat_age_s)} s` : '—');
    // API availability is separate from sensor readiness.
    text('overview-connection', h ? tr('API odpowiada', 'API responding') : tr('API niedostępne', 'API unavailable'));
  }
  renderVision() {
    const camera = this.health?.devices?.camera || this.state?.camera?.activity || this.state?.devices?.camera || this.state?.camera || {};
    const capture = camera?.on === true && !camera.error && camera.offline !== true && camera.stale !== true;
    const frameReady = cameraFrame(this.snap, 'raw').fresh;
    const active = capture || (camera?.vision_enabled === true && frameReady);
    const off = !active && (camera?.vision_enabled === false || camera?.on === false);
    const cameraText = powerLabel(active ? true : off ? false : null);
    const cameraDetails = [cameraText, camera?.mode, Array.isArray(camera?.res) ? camera.res.join('×') : null,
      finite(camera?.fps) ? `${fmt(camera.fps)} fps` : null].filter(Boolean);
    text('d_cam', cameraDetails.join(' · ')); text('camBadge', powerLabel(active ? true : off ? false : null));
    document.getElementById('camBadge')?.classList.toggle('on', active);
    for (const [kind, endpoint] of [['raw', '/vision/cam'], ['proc', '/vision/edge'], ['obst', '/snapshots/obst_annot.jpg'], ['tracker', '/vision/tracker']]) {
      const frame = cameraFrame(this.snap, kind);
      const name = kind === 'raw' ? 'cam' : kind;
      const node = document.getElementById(`img_${name}`);
      const freshFrame = active && frame.fresh;
      // A frame artifact does not prove that its particular producer is on.
      const label = !frame.exists ? tr('brak klatki', 'no frame') : frame.fresh ? frameAge(frame.age) : `${tr('stara klatka', 'old frame')} · ${frameAge(frame.age)}`;
      text(`age_${kind}`, label);
      text(`leg_${name}_txt`, `${kind.toUpperCase()} · ${label}${frame.time_basis === 'file_mtime' ? tr(' · wiek pliku; przechwycenie niepotwierdzone', ' · file age; capture unconfirmed') : ''}`);
      if (!node) continue;
      if (!freshFrame || document.hidden) { node.dataset.frame = ''; if (node.getAttribute('src') !== BLANK) node.src = BLANK; continue; }
      const tag = String(frame.ts);
      if (node.dataset.frame !== tag) {
        node.dataset.frame = tag;
        node.onerror = () => { if (node.dataset.frame === tag) { node.onerror = null; node.src = BLANK; text(`leg_${name}_txt`, `${kind.toUpperCase()} · ${tr('błąd odczytu obrazu', 'image read failed')}`); } };
        node.src = `${endpoint}?v=${encodeURIComponent(tag)}`;
      }
    }
    const o = this.obstacle;
    const valid = presentationReady(o, 3) && typeof o?.present === 'boolean';
    text('obs_present', valid ? String(o.present) : unknown());
    text('obs_conf', valid ? fmt(o.confidence, 3) : '—');
    text('obs_edge', valid ? fmt(o.edge_ratio ?? o.edge_pct, 3) : '—');
    text('obstacle-age', age(o));
    const diag = valid ? o.diag : null;
    text('binsLegendTxt', `LOW/HIGH: ${fmt(diag?.t_low, 2)} / ${fmt(diag?.t_high, 2)} · edge_pct: ${valid ? fmt(diag?.edge_ratio_raw ?? diag?.edge_pct_raw ?? o.edge_ratio ?? o.edge_pct, 3) : '—'}`);
    this.drawBins(diag?.bins, valid ? diag?.edge_ratio_raw ?? diag?.edge_pct_raw ?? o.edge_ratio ?? o.edge_pct : null);
  }
  renderMetrics() {
    for (const key of ['control', 'navigator', 'voice', 'google_home', 'chat', 'face']) {
      const row = this.metrics?.metrics?.[key];
      text(`metric_${key}`, row ? `${row.ok ?? '—'} / ${row.error ?? '—'}` : '—');
    }
    text('metric_total_errors', this.metrics?.total_errors ?? '—');
  }
  axes(id) {
    const canvas = document.getElementById(id), ctx = canvas?.getContext('2d'); if (!ctx) return null;
    const box = { x: 30, y: 10, width: canvas.width - 40, height: canvas.height - 25 };
    ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.strokeStyle = '#284053';
    ctx.strokeRect(box.x, box.y, box.width, box.height); ctx.fillStyle = '#90a4b0'; ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    for (const value of [0, 50, 100]) ctx.fillText(String(value), box.x - 5, box.y + box.height * (1 - value / 100) + 3);
    return { ctx, ...box };
  }
  drawHistory(cpu = [], mem = [], peaks = [], times = []) {
    const axis = this.axes('chart'); if (!axis) return;
    const { ctx, x, y, width, height } = axis;
    const stamps = Array.isArray(times) ? times.slice(-60) : [], newest = stamps[stamps.length - 1];
    for (const [values, color] of [[peaks, '#a17fff'], [cpu, '#6db3ff'], [mem, '#ffd36d']]) {
      if (!Array.isArray(values) || values.length < 2) continue;
      const samples = values.slice(-60); let pen = false;
      ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 1.5;
      samples.forEach((value, i) => {
        if (!finite(value)) { pen = false; return; }
        const stamp = stamps[i];
        if (finite(newest) && finite(stamp) && newest - stamp > 60) { pen = false; return; }
        if (i > 0 && finite(stamp) && finite(stamps[i - 1]) && stamp - stamps[i - 1] > 2) pen = false;
        const position = finite(newest) && finite(stamp) ? Math.max(0, 1 - (newest - stamp) / 60) : i / (samples.length - 1);
        const px = x + width * position, py = y + height * (1 - Math.max(0, Math.min(100, value)) / 100);
        if (pen) ctx.lineTo(px, py); else ctx.moveTo(px, py); pen = true;
      }); ctx.stroke();
    }
  }
  drawBins(bins, edge) {
    const axis = this.axes('binsCanvas'); if (!axis) return;
    const { ctx, x, y, width, height } = axis;
    const samples = Array.isArray(bins) && bins.length ? bins.slice(0, 256) : finite(edge) ? [edge] : [];
    ctx.fillStyle = '#6db3ff';
    samples.forEach((value, i) => { if (finite(value)) { const h = height * Math.max(0, Math.min(1, value)); ctx.fillRect(x + width * i / samples.length, y + height - h, Math.max(1, width / samples.length - 2), h); } });
  }
}
