import { requestId } from './request-id.js';
import { request, poll } from './transport.js';
import { tr, showError } from './ui.js';
import { readMjpeg } from './mjpeg.js';

const ENDPOINT = '/api/resource/camera/pipeline';
const pending = state => ['starting', 'stopping', 'waiting_frame'].includes(state);
const stateName = state => ({
  stopped: tr('Wyłączona', 'Stopped'), stopping: tr('Zatrzymywanie', 'Stopping'),
  starting: tr('Uruchamianie', 'Starting'), waiting_frame: tr('Czeka na klatkę', 'Waiting for frame'),
  active: tr('Aktywna', 'Active'), failed: tr('Błąd kamery', 'Camera error'),
})[state] || state;
export function validPipeline(value) {
  return value?.contract_id === 'rider.camera_pipeline' && value.contract_version === 1
    && Number.isInteger(value.revision) && value.revision >= 1
    && ['local', 'venom'].includes(value.profile?.analysis_location)
    && ['canny', 'ssd', 'tflite'].includes(value.profile?.local_engine)
    && ['snapshots', 'mjpeg'].includes(value.profile?.remote_transport)
    && typeof value.capabilities === 'object' && typeof value.state === 'string';
}
export class CameraPipelineControls {
  constructor(target, onState = () => {}) {
    this.status = null; this.busy = false; this.onState = onState; this.readEpoch = 0;
    this.node = document.createElement('section'); this.node.className = 'camera-pipeline-controls';
    this.node.innerHTML = '<h3></h3><div class="operator-row"><label><span class="location-label"></span><select class="location"></select></label>'
      + '<label class="engine-field"><span class="engine-label"></span><select class="engine"></select></label>'
      + '<label class="transport-field"><span class="transport-label"></span><select class="transport"></select></label>'
      + '<button type="button" class="c-btn power"></button></div><p class="pipeline-status" role="status"></p><p class="pipeline-error" role="alert"></p>';
    target.before(this.node);
    for (const [name, field] of [['location', 'analysis_location'], ['engine', 'local_engine'], ['transport', 'remote_transport']])
      this.node.querySelector('.' + name).addEventListener('change', event => {
        if (this.status) void this.change('configure', { ...this.status.profile, [field]: event.target.value });
      });
    this.node.querySelector('.power').addEventListener('click', () => {
      if (this.status) void this.change(['active', 'starting', 'waiting_frame'].includes(this.status.state) ? 'stop' : 'start');
    });
    this.poller = poll(() => this.load(), { interval: 1000, onError: error => {
      this.onState(null); this.error = error.message; this.render();
    } });
    window.addEventListener('dashboard:langchange', () => this.render());
    window.addEventListener('pagehide', () => this.poller.stop());
    this.render();
  }
  async load() {
    if (this.busy) return;
    const epoch = this.readEpoch;
    try {
      const result = await request(ENDPOINT);
      if (epoch !== this.readEpoch) return;
      if (!validPipeline(result.data)) throw new Error('camera_pipeline_invalid_status');
      this.status = { ...result.data, preview_anchor: {
        latest: result.data.latest_frame, receivedAt: performance.now(),
        roundTripMs: Math.max(0, (result.received_at - result.sent_at) * 1000),
      } }; this.onState(this.status); this.render();
    } catch (error) {
      if (error.status === 404) { this.node.hidden = true; this.onState(undefined); return; }
      throw error;
    }
  }
  async change(action, profile) {
    if (this.busy || !this.status) return;
    this.busy = true; this.error = ''; this.readEpoch++; this.onState(null); this.render();
    try {
      const response = await request(ENDPOINT, { method: 'POST', timeout: 20000, body: {
        contract_version: 1, request_id: requestId('camera'), expected_revision: this.status.revision,
        action, ...(action === 'configure' ? { profile } : {}),
      } });
      if (!validPipeline(response.data)) throw new Error('camera_pipeline_invalid_status');
      this.status = response.data; this.onState(this.status);
    } catch (error) { this.error = error.message; showError(error); }
    finally { this.readEpoch++; this.busy = false; this.render(); void this.poller.refresh(); }
  }
  options(name, choices, selected, supported) {
    const select = this.node.querySelector('.' + name);
    // Preserve focus and selection while status polls update.
    const key = JSON.stringify([choices, selected, supported]);
    if (select.dataset.options !== key) {
      select.dataset.options = key;
      select.replaceChildren(...choices.map(([value, label]) => {
        const option = document.createElement('option'); option.value = value; option.textContent = label;
        option.disabled = !supported.includes(value); option.selected = selected === value; return option;
      }));
    }
    select.disabled = this.busy || !this.status || pending(this.status.state);
  }
  render() {
    const status = this.status, caps = status?.capabilities || {}, profile = status?.profile || {};
    this.node.querySelector('h3').textContent = tr('Tor kamery', 'Camera pipeline');
    for (const [cls, pl, en] of [['location', 'Analiza obrazu', 'Image analysis'], ['engine', 'Model lokalny', 'Local engine'], ['transport', 'Obraz do Venom', 'Image transport to Venom']])
      this.node.querySelector('.' + cls + '-label').textContent = tr(pl, en);
    this.options('location', [['local', tr('Lokalnie na Pi', 'Local on Pi')], ['venom', 'Venom']], profile.analysis_location, caps.analysis_locations || []);
    this.options('engine', ['canny', 'ssd', 'tflite'].map(value => [value, value.toUpperCase()]), profile.local_engine, caps.local_engines || []);
    this.options('transport', [['snapshots', tr('Klatki JPEG', 'JPEG snapshots')], ['mjpeg', tr('Natywny MJPEG', 'Native MJPEG')]], profile.remote_transport, caps.remote_transports || []);
    this.node.querySelector('.engine-field').hidden = profile.analysis_location !== 'local';
    this.node.querySelector('.transport-field').hidden = profile.analysis_location !== 'venom';
    const power = this.node.querySelector('.power'); power.disabled = !status || this.busy || status.state === 'stopping';
    power.textContent = ['active', 'starting', 'waiting_frame'].includes(status?.state) ? tr('Kamera OFF', 'Camera OFF') : tr('Kamera ON', 'Camera ON');
    this.node.querySelector('.pipeline-status').textContent = status
      ? stateName(status.state) + ' · r' + status.revision + ' · ' + Object.entries(status.effective_stages || {}).filter(([, active]) => active).map(([name]) => name).join(', ')
      : tr('Odczytywanie profilu z Pi…', 'Reading profile from Pi…');
    this.node.querySelector('.pipeline-error').textContent = this.error || status?.error || '';
  }
}

/** Only reads an explicitly running producer. Never starts camera, model or motion. */
export class PipelinePreview {
  constructor(image, { empty = null, status = null, kind = 'raw' } = {}) {
    this.image = image; this.empty = empty; this.label = status; this.kind = kind;
    this.identity = ''; this.epoch = 0; this.objectUrl = null;
    this.canvas = document.createElement('canvas'); this.canvas.hidden = true;
    this.canvas.style.cssText = 'width:100%;max-height:70vh;object-fit:contain;display:none';
    this.canvas.setAttribute('role', 'img'); this.canvas.setAttribute('aria-label', tr('Bieżący obraz kamery', 'Current camera image'));
    image.after(this.canvas);
    this.expiry = setInterval(() => {
      if (this.shown && performance.now() - this.shown.receivedAt + this.shown.ageMs > 1000) this.stale();
    }, 250);
    document.addEventListener('visibilitychange', () => { this.close(); if (!document.hidden) void this.run(); });
    window.addEventListener('pagehide', () => { this.close(); clearInterval(this.expiry); });
  }
  update(profile, kind = this.kind, enabled = true) {
    if (profile?.compatibility_mode === 'legacy') profile = undefined;
    if (profile?.preview_anchor) this.anchor = profile.preview_anchor;
    this.profile = profile; this.kind = kind; this.enabled = enabled;
    const key = JSON.stringify([profile?.revision, profile?.transport_epoch, profile?.camera_session, profile?.state, profile?.profile, kind, enabled]);
    if (key === this.identity) return;
    this.identity = key; this.close();
    if (profile !== undefined) this.image.dataset.pipelineManaged = 'true';
    else { delete this.image.dataset.pipelineManaged; this.canvas.style.display = 'none'; return; }
    this.image.hidden = true; this.image.removeAttribute('src'); void this.run();
  }
  close() { this.epoch++; clearTimeout(this.retry); this.abort?.abort(); this.stale(); }
  stale() {
    this.shown = null; this.canvas.hidden = true; this.canvas.style.display = 'none';
    if (this.empty) this.empty.hidden = false;
    if (this.label) this.label.textContent = tr('Brak świeżego obrazu — podgląd zatrzymany', 'No fresh image — preview stopped');
  }
  async display(part, signal, current) {
    const source = JSON.parse(part.headers.get('X-Rider-Source') || '{}');
    if (source.contract_version !== 1 || !Number.isInteger(source.sequence)
      || !Number.isFinite(source.frame_age_ms) || source.frame_age_ms < 0
      || source.camera_session !== this.profile?.camera_session || source.transport_epoch !== this.profile?.transport_epoch
      || source.pipeline_revision !== this.profile?.revision) throw new Error('camera_source_mismatch');
    const receivedAt = part.receivedAt;
    let ageMs = source.frame_age_ms;
    const anchor = this.anchor, latest = anchor?.latest;
    if (!latest || latest.camera_session !== source.camera_session || latest.transport_epoch !== source.transport_epoch
      || latest.pipeline_revision !== source.pipeline_revision) throw new Error('camera_age_unavailable');
    if (latest && latest.camera_session === source.camera_session && latest.transport_epoch === source.transport_epoch
      && latest.pipeline_revision === source.pipeline_revision && Number.isFinite(latest.captured_monotonic_ns)
      && Number.isFinite(anchor.roundTripMs)) {
      ageMs = Math.max(ageMs, latest.frame_age_ms + anchor.roundTripMs + receivedAt - anchor.receivedAt
        - (source.captured_monotonic_ns - latest.captured_monotonic_ns) / 1e6);
    }
    const identity = source.camera_session + ':' + source.transport_epoch;
    if (identity === this.lastSource?.identity && source.sequence <= this.lastSource.sequence) return;
    if (ageMs + performance.now() - receivedAt > 1000) return;
    const url = URL.createObjectURL(new Blob([part.bytes], { type: 'image/jpeg' }));
    try {
      const image = new Image(); image.src = url; await image.decode();
      if (signal.aborted || !current() || ageMs + performance.now() - receivedAt > 1000) return;
      const transform = source.image_transform, rotation = transform?.rotation || 0;
      this.canvas.width = rotation % 180 ? image.height : image.width;
      this.canvas.height = rotation % 180 ? image.width : image.height;
      const context = this.canvas.getContext('2d');
      context.translate(this.canvas.width / 2, this.canvas.height / 2);
      context.scale(transform?.flip_h ? -1 : 1, transform?.flip_v ? -1 : 1);
      context.rotate(rotation * Math.PI / 180); context.drawImage(image, -image.width / 2, -image.height / 2);
      this.lastSource = { identity, sequence: source.sequence };
      this.shown = { ageMs, receivedAt }; this.canvas.hidden = false; this.canvas.style.display = '';
      this.image.hidden = true; if (this.empty) this.empty.hidden = true;
      if (this.label) this.label.textContent = this.kind.toUpperCase() + ' · ' + tr('bieżąca klatka', 'current frame')
        + ' · ' + source.sequence + ' · ' + Math.round(ageMs + performance.now() - receivedAt) + ' ms';
    } finally { URL.revokeObjectURL(url); }
  }
  async run() {
    const p = this.profile;
    if (!p || !this.enabled || document.hidden || !['active', 'waiting_frame'].includes(p.state)
      || this.kind === 'proc' && p.profile.analysis_location !== 'local') return;
    const epoch = ++this.epoch, abort = new AbortController(); this.abort = abort;
    const current = () => epoch === this.epoch && !abort.signal.aborted && !document.hidden;
    const native = this.kind === 'raw' && p.profile.analysis_location === 'venom' && p.profile.remote_transport === 'mjpeg';
    let gap, latest = null, busy = false;
    const pump = async () => {
      if (busy) return; busy = true;
      try { while (latest && current()) { const part = latest; latest = null; await this.display(part, abort.signal, current); } }
      catch { if (current()) this.stale(); } finally { busy = false; }
    };
    try {
      gap = setTimeout(() => abort.abort(), 5000);
      const response = await fetch(native ? '/api/resource/camera/stream.mjpg' : '/api/resource/camera/frame?view=' + this.kind, { cache: 'no-store', signal: abort.signal });
      if (!response.ok) throw new Error('camera_frame_unavailable');
      if (native) await readMjpeg(response, abort.signal, part => {
        clearTimeout(gap); gap = setTimeout(() => abort.abort(), 3000);
        latest = part; void pump();
      });
      else {
        const receivedAt = performance.now(), bytes = new Uint8Array(await response.arrayBuffer());
        await this.display({ headers: response.headers, bytes, receivedAt }, abort.signal, current);
      }
    } catch { if (current()) this.stale(); }
    finally {
      clearTimeout(gap); latest = null; abort.abort();
      if (epoch === this.epoch && !document.hidden) {
        if (native) this.stale();
        this.retry = setTimeout(() => { void this.run(); }, native ? 1000 : 500);
      }
    }
  }
}
