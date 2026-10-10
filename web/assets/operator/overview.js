import { request, poll } from './transport.js';
import { ageOf, fresh, presentationReady, cameraFrame, catalogKnown } from './model.js';
import { el, text, tr, statusLabel } from './ui.js';
import { telemetryChannel } from './devices.js?v=overview-restored-2';

const finite = value => typeof value === 'number' && Number.isFinite(value);
const fmt = (value, digits = 1) => finite(value) ? value.toFixed(digits) : '—';
const age = row => ageOf(row) === null ? '—' : `${ageOf(row).toFixed(1)} s`;
const frameAge = seconds => !finite(seconds) ? '—' : seconds >= 86400 ? `${Math.floor(seconds / 86400)} ${tr('dni', 'days')}` : seconds >= 3600 ? `${fmt(seconds / 3600)} h` : `${fmt(seconds)} s`;
const unknown = () => tr('brak / stary pomiar', 'missing / stale reading');
const BLANK = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"%3E%3Crect width="640" height="360" fill="%2306090d"/%3E%3C/svg%3E';

// Read-only measurements dashboard. No task, camera or actuator is started here.
export class Overview {
  constructor(safety) {
    this.safety = safety;
    this.state = null; this.health = null; this.system = null; this.catalog = null;
    this.snap = null; this.obstacle = null; this.metrics = null;
    this.poller = poll(async () => {
      const results = await Promise.allSettled(['/healthz', '/sysinfo', '/api/logic/catalog']
        .map(path => request(path)));
      [this.health, this.system, this.catalog] = results.map(result => result.status === 'fulfilled' ? result.value.data : null);
      this.render();
    }, { interval: 2000 });
    // One small telemetry read per second avoids expiring healthy 1 Hz samples
    // between refreshes. Filesystem/image metadata remains on its slower poll.
    this.telemetryPoller = poll(async () => {
      try { this.state = (await request('/state')).data; }
      catch { this.state = null; }
      this.renderTelemetry();
      window.dashboardFooter?.update({ state: this.state });
      if (this.state) window.dispatchEvent(new CustomEvent('dashboard:update', { detail: this.state }));
    }, { interval: 1000 });
    this.visionPoller = poll(async () => {
      const results = await Promise.allSettled([request('/vision/snap-info?light=1'), request('/vision/obstacle')]);
      [this.snap, this.obstacle] = results.map(result => result.status === 'fulfilled' ? result.value.data : null);
      this.renderVision();
    }, { interval: 2000 });
    poll(async () => {
      try { this.metrics = (await request('/api/app-metrics')).data; }
      catch { this.metrics = null; }
      this.renderMetrics();
    }, { interval: 10000 });
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
    this.drawHistory(usable ? si.hist_cpu : [], usable ? si.hist_mem : []);
  }
  channel(name) {
    const parent = this.safety.state, channel = parent?.sensor_quality?.sensors?.[name];
    const maxAge = Math.min(3, parent?.sensor_quality?.max_age_s || 2.5);
    if (fresh(parent) && channel?.ready === true && !channel.error && fresh(channel, maxAge) && finite(channel.value)) return channel;
    return null;
  }
  renderTelemetry() {
    const xgo = this.state?.devices?.xgo;
    const ready = presentationReady(xgo);
    const samples = Object.fromEntries(['roll', 'pitch', 'yaw', 'battery'].map(key => [key, telemetryChannel(xgo, key)]));
    const values = ['roll', 'pitch', 'yaw'].map(key => samples[key].ready && finite(xgo?.[key]) ? xgo[key] : null);
    // /state battery_pct is already percent. Only the safety battery channel is a ratio.
    const batteryChannel = this.channel('battery');
    const battery = batteryChannel && batteryChannel.value >= 0 && batteryChannel.value <= 1
      ? batteryChannel.value * 100 : samples.battery.ready ? samples.battery.value : null;
    const quality = this.safety.state?.sensor_quality?.sensors;
    const imuReady = ['roll', 'pitch', 'yaw'].every(key => samples[key].ready) || (!quality && ready && values.every(finite));
    text('d_xgo_imu', imuReady ? tr('Świeży odczyt', 'Fresh reading') : values.some(finite) ? tr('Częściowy odczyt', 'Partial reading') : unknown());
    text('d_xgo_pose', values.some(finite) ? `R ${fmt(values[0])} · P ${fmt(values[1])} · Y ${fmt(values[2])}` : '—');
    text('d_xgo_batt', finite(battery) ? `${fmt(battery, 0)}% · ${age(batteryChannel || samples.battery)}` : unknown());
    text('xgo-age', `${age(xgo)}${ready ? '' : ` · ${unknown()}`}`);
    const rawYaw = this.channel('yaw');
    text('imu-yaw-raw', rawYaw ? `${fmt(rawYaw.value, 2)} · ${age(rawYaw)}` : samples.yaw.ready && finite(xgo?.yaw_raw) ? `${fmt(samples.yaw.value, 2)} · ${age(samples.yaw)}` : unknown());
    text('ci_fw', xgo?.fw || this.health?.devices?.xgo?.fw || '—');
    const lcd = this.state?.devices?.lcd || this.health?.devices?.lcd;
    const lcdStatus = lcd?.on === true ? tr('Aktywny', 'Active') : lcd?.on === false ? 'OFF' : tr('Stan nieznany', 'State unknown');
    text('d_lcd', lcdStatus);
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
    const camera = { ...this.health?.devices?.camera, ...this.state?.devices?.camera, ...this.state?.camera };
    const capture = camera?.on === true && !camera.error && camera.offline !== true && camera.stale !== true;
    const frameReady = cameraFrame(this.snap, 'raw').fresh;
    const active = capture || (camera?.vision_enabled === true && frameReady);
    const off = !active && (camera?.vision_enabled === false || camera?.on === false);
    const cameraText = active ? tr('Włączona', 'Enabled') : off ? tr('Wyłączona — na żądanie', 'Off — on demand') : tr('Stan nieznany', 'State unknown');
    const cameraDetails = [cameraText, camera?.mode, Array.isArray(camera?.res) ? camera.res.join('×') : null,
      finite(camera?.fps) ? `${fmt(camera.fps)} fps` : null].filter(Boolean);
    text('d_cam', cameraDetails.join(' · ')); text('camBadge', active ? 'ON' : off ? 'OFF' : '—');
    document.getElementById('camBadge')?.classList.toggle('on', active);
    for (const [kind, endpoint] of [['raw', '/vision/cam'], ['proc', '/vision/edge'], ['obst', '/snapshots/obst_annot.jpg'], ['tracker', '/vision/tracker']]) {
      const frame = cameraFrame(this.snap, kind);
      const name = kind === 'raw' ? 'cam' : kind;
      const node = document.getElementById(`img_${name}`);
      const freshFrame = active && frame.fresh;
      const label = !frame.exists ? tr('brak klatki', 'no frame') : freshFrame ? frameAge(frame.age) : `${tr('stara klatka', 'old frame')} · ${frameAge(frame.age)}`;
      text(`age_${kind}`, label);
      text(`leg_${name}_txt`, `${kind.toUpperCase()} · ${cameraText} · ${label}`);
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
    text('obs_edge', valid ? fmt(o.edge_pct, 3) : '—');
    text('obstacle-age', age(o));
    const diag = valid ? o.diag : null;
    text('binsLegendTxt', `LOW/HIGH: ${fmt(diag?.t_low, 2)} / ${fmt(diag?.t_high, 2)} · edge_pct: ${valid ? fmt(diag?.edge_pct_raw ?? o.edge_pct, 3) : '—'}`);
    this.drawBins(diag?.bins, valid ? diag?.edge_pct_raw ?? o.edge_pct : null);
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
  drawHistory(cpu = [], mem = []) {
    const axis = this.axes('chart'); if (!axis) return;
    const { ctx, x, y, width, height } = axis;
    for (const [values, color] of [[cpu, '#6db3ff'], [mem, '#ffd36d']]) {
      if (!Array.isArray(values) || values.length < 2) continue;
      const samples = values.slice(-60); let pen = false;
      ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 1.5;
      samples.forEach((value, i) => {
        if (!finite(value)) { pen = false; return; }
        const px = x + width * i / (samples.length - 1), py = y + height * (1 - Math.max(0, Math.min(100, value)) / 100);
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
