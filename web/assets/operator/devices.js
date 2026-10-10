import { cameraFrame, fresh, presentationReady, displayValue, ageOf } from './model.js';
import { request, poll } from './transport.js';
import { el, freshPill, pill, kv, tr, ageStamp, text, showError, rawDetails } from './ui.js';
export function telemetryChannel(xgo, name, unavailable = false) {
  const quality = xgo?.sensor_quality?.sensors || xgo?.sensor_quality || {};
  const channel = quality[name];
  const times = xgo?.sensor_observed_at || {};
  const independent = channel && typeof channel === 'object';
  const at = independent && Object.hasOwn(channel, 'observed_at') ? channel.observed_at
    : Object.hasOwn(times, name) ? times[name]
      : name === 'battery' && Object.hasOwn(xgo || {}, 'battery_observed_at') ? xgo.battery_observed_at
        : xgo && Object.hasOwn(xgo, 'observed_at') ? xgo.observed_at : xgo?.ts;
  const row = { ...(independent ? channel : {}), observed_at: at,
    offline: unavailable || xgo?.offline === true, error: channel?.error || xgo?.error,
    stale: independent ? channel.stale === true : xgo?.stale === true,
    source: channel?.source || xgo?.source || 'unknown' };
  const value = name === 'battery' ? xgo?.battery_pct : name === 'yaw' ? xgo?.yaw_raw ?? xgo?.yaw : xgo?.[name];
  const good = typeof value === 'number' && Number.isFinite(value)
    && (name !== 'battery' || value >= 0 && value <= 100)
    && (!independent || channel.ready === true) && presentationReady(row, 2.5)
    && (name !== 'battery' || xgo?.battery_ok !== false);
  return { ...row, value, ready: good };
}
export class Devices {
  constructor() {
    this.imageBusy = false; this.preview = false; this.meta = null; this.lastFrame = null; this.displayed = null; this.pendingImage = null;
    this.xgo = null; this.telemetryUnavailable = true; this.resourceRows = [];
    this.image = document.getElementById('camera-image');
    this.image?.addEventListener('load', () => { this.displayed = this.pendingImage; this.pendingImage = null; this.imageBusy = false; clearTimeout(this.imageTimeout); this.renderPreview(); });
    this.image?.addEventListener('error', () => { this.pendingImage = null; this.displayed = null; this.imageBusy = false; clearTimeout(this.imageTimeout); this.lastFrame = null; text('camera-display-age', tr('Nie udało się wczytać klatki', 'Frame load failed')); });
    this.expiry = setInterval(() => { if (!document.hidden) { this.renderPreview(); this.renderTelemetry(); } }, 1000);
    window.addEventListener('pagehide', () => {
      clearInterval(this.expiry); clearTimeout(this.imageTimeout);
      this.poller.stop(); this.telemetryPoller.stop(); this.previewPoller.stop();
    });
    document.getElementById('preview-toggle')?.addEventListener('click', () => { this.preview = !this.preview; this.renderPreview(); });
    document.getElementById('preview-refresh')?.addEventListener('click', () => this.fetchFrame());
    document.getElementById('preview-kind')?.addEventListener('change', () => { this.lastFrame = null; this.frame(); });
    document.getElementById('preview-url-form')?.addEventListener('submit', event => {
      event.preventDefault(); this.lastFrame = null; this.fetchFrame();
    });
    this.poller = poll(() => this.load(), { interval: 10000, onError: showError,
      onVisibility: hidden => { if (hidden) { this.preview = false; this.renderPreview(); } } });
    this.telemetryPoller = poll(() => this.loadTelemetry(), { interval: 1000,
      onError: error => { this.telemetryUnavailable = true; this.renderTelemetry(); showError(error); } });
    this.previewPoller = poll(async () => {
      if (!this.preview) return;
      this.meta = (await request('/vision/snap-info?light=1')).data; this.renderPreview();
    }, { interval: 2000, onError: error => { this.meta = null; this.renderPreview(); showError(error); } });
  }
  async fetchFrame() {
    try { this.meta = (await request('/vision/snap-info?light=1')).data; this.renderPreview(); this.frame(true); }
    catch (error) { this.meta = null; this.renderPreview(); showError(error); }
  }
  async load() {
    const target = document.getElementById('device-list');
    const [snapResult, ...resources] = await Promise.allSettled([
      request('/vision/snap-info?light=1'), ...['camera', 'mic', 'speaker', 'lcd', 'uart'].map(name => request(`/api/resource/${name}`))
    ]);
    this.meta = snapResult.status === 'fulfilled' ? snapResult.value.data : null;
    const rows = resources.map((result, index) => {
      const name = ['camera', 'mic', 'speaker', 'lcd', 'uart'][index];
      const data = result.status === 'fulfilled' ? result.value.data : { state: 'unknown', error: result.reason.message, observed_at: null };
      const card = el('article', 'c-card'); const good = fresh(data, 10) && data.state !== 'unknown' && data.state !== 'unavailable' && !data.error;
      card.append(el('h3', '', name.toUpperCase()), freshPill(data, good ? data.state : 'unknown', good ? data.state === 'free' ? 'ok' : 'warn' : 'err'),
        kv([[tr('Źródło', 'Source'), data.source || 'unknown'], [tr('Wiek odczytu', 'Observation age'), ageStamp(data, 10)],
          [tr('Konsumenci zadań', 'Task consumers'), (data.consumers || []).join(', ') || '—'],
          [tr('Właściciele procesów', 'Process owners'), (data.holders || []).map(row => `${row.service || row.cmd || row.command || '?'} (PID ${row.pid})`).join(', ') || (good && data.state === 'free' ? tr('brak', 'none') : tr('nieznani', 'unknown'))]]));
      if (name === 'lcd') card.append(el('p', 'operator-muted', tr('Ekran zamontowany bokiem. Kompensacja 270°; nie zmieniaj orientacji w panelu.', 'Display mounted sideways. Compensation 270°; preserve orientation.')));
      if (name === 'uart') card.append(el('p', 'operator-muted', tr('Jeden właściciel UART: wykonawca ruchu. Telemetria przez BUS.', 'One UART owner: motion executor. Telemetry through BUS.')));
      if (data.error) card.append(el('p', 'operator-error', data.error));
      card.append(rawDetails(data)); return card;
    });
    this.resourceRows = rows;
    if (document.getElementById('telemetry-list')) target?.replaceChildren(...rows);
    else if (target) {
      // Cached older markup has one list for measurements and resource owners.
      try { await this.loadTelemetry(); }
      catch (error) { this.telemetryUnavailable = true; this.renderTelemetry(); showError(error); }
    }
    this.renderPreview();
  }
  async loadTelemetry() {
    const data = (await request('/state')).data;
    if (data?.error) throw new Error(data.error);
    this.xgo = data?.devices?.xgo || null; this.telemetryUnavailable = false;
    this.renderTelemetry();
  }
  renderTelemetry() {
    const measurements = document.getElementById('telemetry-list');
    const target = measurements || document.getElementById('device-list'); if (!target) return;
    const xgo = this.xgo;
    const samples = Object.fromEntries(['roll', 'pitch', 'yaw', 'battery'].map(name => [name, telemetryChannel(xgo, name, this.telemetryUnavailable)]));
    const axes = ['roll', 'pitch', 'yaw'].map(name => samples[name]);
    const readyAxes = axes.filter(row => row.ready).length;
    const imuAt = axes.every(row => typeof row.observed_at === 'number') ? Math.min(...axes.map(row => row.observed_at)) : null;
    const label = readyAxes === 3 ? tr('IMU: świeży transport', 'IMU: fresh transport')
      : readyAxes ? tr('IMU: częściowy odczyt', 'IMU: partial reading') : tr('IMU: brak / stare dane', 'IMU: missing / stale data');
    const telemetry = el('article', 'c-card');
    telemetry.append(el('h3', '', tr('Bateria i IMU', 'Battery and IMU')),
      pill(label, readyAxes === 3 ? 'ok' : 'warn'));
    const reading = (row, unit) => `${displayValue(row.value, unit)} · ${row.ready ? tr('świeży odczyt', 'fresh reading')
      : tr('niepotwierdzony / stary', 'unconfirmed / stale')}`;
    telemetry.append(kv([
      [tr('Firmware (zapamiętane)', 'Firmware (cached)'), displayValue(xgo?.fw)],
      [tr('Źródło', 'Source'), xgo?.source || 'unknown'], [tr('Właściciel UART', 'UART owner'), xgo?.uart_owner || 'unknown'],
      [tr('Bateria', 'Battery'), reading(samples.battery, '%')], [tr('Wiek baterii', 'Battery age'), ageStamp(samples.battery, 2.5)],
      ...['roll', 'pitch', 'yaw'].flatMap(name => [[name === 'yaw' ? xgo?.yaw_raw != null ? tr('Yaw surowy', 'Raw yaw') : tr('Yaw (prezentacja)', 'Yaw (presentation)') : name,
        reading(samples[name], name === 'yaw' ? '' : '°')], [`${name} · ${tr('wiek', 'age')}`, ageStamp(samples[name], 2.5)]]),
      [tr('Yaw zawinięty (prezentacja)', 'Wrapped yaw (presentation)'), displayValue(xgo?.yaw, '°')],
      [tr('Wiek całego IMU', 'Complete IMU age'), ageOf({ observed_at: imuAt }) === null ? tr('nieznany', 'unknown') : ageStamp({ observed_at: imuAt }, 2.5)]
    ]), el('p', 'operator-muted', tr('Świeży transport nie potwierdza poprawności fizycznej pomiaru. Semantyka surowego yaw wymaga weryfikacji; zawinięcie nie koryguje sensora.',
      'Fresh transport does not validate the physical measurement. Raw yaw semantics require verification; wrapping does not correct the sensor.')));
    const source = rawDetails(xgo); source.open = target.querySelector?.('details')?.open === true;
    telemetry.append(source); target.replaceChildren(telemetry, ...(measurements ? [] : this.resourceRows));
  }
  renderPreview() {
    text('preview-toggle', this.preview ? tr('Wyłącz odświeżanie obrazu', 'Disable image refresh') : tr('Włącz odświeżanie obrazu', 'Enable image refresh'));
    text('camera-preview-state', this.preview ? tr('Podgląd włączony w tej karcie', 'Preview enabled in this tab') : tr('Podgląd wyłączony w tej karcie', 'Preview disabled in this tab'));
    const kind = document.getElementById('preview-kind')?.value || 'raw';
    const frame = cameraFrame(this.meta, kind);
    text('camera-age', `${kind.toUpperCase()} · ${frame.age === null ? tr('wiek nieznany', 'age unknown') : `${frame.age.toFixed(1)} s`} · ${frame.fresh ? tr('świeża klatka', 'fresh frame') : tr('brak / stara klatka', 'missing / stale frame')}`);
    const displayed = cameraFrame({ ...this.meta, shown: { exists: this.displayed !== null, observed_at: this.displayed?.ts } }, 'shown');
    text('camera-display-age', `${tr('Wyświetlana klatka', 'Displayed frame')}: ${this.displayed?.kind?.toUpperCase() || '—'} · ${displayed.age?.toFixed(1) ?? '—'} s${displayed.fresh ? '' : ' · unknown / stale'}`);
    this.image?.classList.toggle('operator-stale-frame', !displayed.fresh);
    this.frame();
  }
  frame(once = false) {
    if (!this.image || this.imageBusy || document.hidden || (!this.preview && !once)) return;
    const kind = document.getElementById('preview-kind').value;
    const frame = cameraFrame(this.meta, kind);
    if (!frame.exists || frame.age === null) return;
    const custom = document.getElementById('preview-url').value.trim();
    const defaults = { raw: '/vision/cam', proc: '/vision/edge', ssd: '/vision/ssd', tracker: '/vision/tracker' };
    let url;
    try {
      url = new URL(custom || defaults[kind], location.origin);
      if (!['http:', 'https:'].includes(url.protocol) || url.origin !== location.origin || !/^\/(camera|vision|snapshots)\//.test(url.pathname)) throw new Error('URL must be a local camera snapshot');
    } catch (error) { showError(error); return; }
    const key = `${url.pathname}:${frame.ts}`;
    if (!once && this.lastFrame === key) return;
    url.searchParams.set('t', frame.ts); this.lastFrame = key; this.imageBusy = true; this.pendingImage = { ts: frame.ts, kind, url: url.href };
    this.image.src = url.href; this.image.hidden = false;
    // Broken endpoints cannot permanently block the preview loop.
    clearTimeout(this.imageTimeout); this.imageTimeout = setTimeout(() => {
      this.image.removeAttribute('src'); this.image.hidden = true; this.imageBusy = false; this.pendingImage = null; this.displayed = null; this.lastFrame = null;
      text('camera-display-age', tr('Timeout obrazu; brak potwierdzonej klatki', 'Image timeout; no confirmed frame'));
    }, 6000);
  }
}
