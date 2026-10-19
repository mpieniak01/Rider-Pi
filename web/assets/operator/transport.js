import { API_ACCEPT, decodeResponse, errorMessage, responseFamily } from './contract.js';
import { setServerClock } from './model.js';
const reads = new Map(), cachedReads = new Map();
let readGeneration = 0;
// Presentation only: motion renewal, watchdog and safety polling are separate.
const intervalLimits = { telemetry: 1000, system: 2000, services: 5000, inventory: 10000, vision: 2000, metrics: 10000 };
const panelIntervals = { ...intervalLimits };
const phases = { telemetry: 0, services: 250, system: 500, vision: 750, inventory: 250, metrics: 500 };
function rememberSampling(data) {
  const incoming = data?.sampling?.panel_intervals_ms;
  if (!incoming) return;
  for (const [name, fallback] of Object.entries(intervalLimits)) {
    const value = incoming[name];
    if (Number.isFinite(value) && value >= 1000 && value <= fallback) panelIntervals[name] = value;
  }
}
export function invalidateReads() {
  readGeneration++; cachedReads.clear(); reads.clear();
}
let contractProof = null;
function rememberContract(decoded, response, receivedAt) {
  const { data, meta } = decoded;
  const age = meta?.server_time - meta?.observed_at;
  const valid = response.status === 200 && decoded.canonical && meta.contract_id === 'rider.catalog'
    && meta.contract_version === 2 && typeof meta.observed_at === 'number' && Number.isFinite(age) && age >= 0 && age <= 10
    && data?.ok === true && data.contract_version === 2 && data.catalog_version === 2
    && Array.isArray(data.features) && Array.isArray(data.units)
    && Array.isArray(data.api_envelope_versions) && data.api_envelope_versions.includes(1)
    && !data.error && data.offline !== true && data.stale !== true;
  contractProof = valid ? { receivedAt } : null;
}
// Complete contract negotiation before creating a 500 ms command envelope.
export async function prepareMutation({ control = false } = {}) {
  if (control && contractProof) return;
  const age = Date.now() / 1000 - (contractProof?.receivedAt ?? 0);
  if (!contractProof || age < 0 || age > 5) await request('/api/logic/catalog', { force: true });
  if (!contractProof) throw Object.assign(new Error('Unsupported Rider contract; read only'), { status: 409 });
}
export function request(path, options = {}) {
  const method = options.method || 'GET', generation = readGeneration;
  const cacheable = method === 'GET' && path === '/api/logic/catalog';
  const previous = cachedReads.get(path), age = Date.now() - (previous?.at ?? 0);
  if (cacheable && !options.force && previous && age >= 0 && age < 1000)
    return Promise.resolve(previous.value);
  if (method === 'GET' && reads.has(path)) return reads.get(path);
  if (method !== 'GET') invalidateReads();
  const flight = performRequest(path, options);
  if (method === 'GET') {
    reads.set(path, flight);
    const clear = () => { if (reads.get(path) === flight) reads.delete(path); };
    flight.then(value => {
      clear();
      if (cacheable && generation === readGeneration) cachedReads.set(path, { at: Date.now(), value });
    }, () => { clear(); if (generation === readGeneration) cachedReads.delete(path); });
  } else flight.then(invalidateReads, invalidateReads);
  return flight;
}
function validateResponseMime(decoded,response,path) {
    if (decoded.canonical) {
      const mime = (response.headers?.get?.('content-type') || '').toLowerCase();
      if (mime.split(';')[0].trim() !== 'application/vnd.rider.api+json'
        || !/;\s*version\s*=\s*(?:1|"1")\s*(?:;|$)/.test(mime)) {
        if (path === '/api/logic/catalog') contractProof = null;
        throw Object.assign(new Error('Unsupported Rider response Content-Type; read only'), { status: 502 });
      }
    }
}
async function performRequest(path, { method = 'GET', body, timeout = 6000, beforeSend = () => {} } = {}) {
  const stop = path === '/api/control' && body?.action === 'stop'
    || path === '/api/safety' && ['disarm', 'estop'].includes(body?.action);
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !stop) {
    await prepareMutation({ control: path === '/api/control' || path === '/api/safety' });
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const sentAt = Date.now() / 1000;
  try {
    beforeSend();
    const response = await fetch(path, { method, cache: 'no-store', signal: controller.signal,
      headers: body === undefined ? { Accept: API_ACCEPT } : { Accept: API_ACCEPT, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body) });
    const payload = await response.json();
    const decoded = decodeResponse(payload, response.status, responseFamily(path)), { data, meta, operation } = decoded;
    validateResponseMime(decoded,response,path);
    const receivedAt = Date.now() / 1000;
    if (path === '/api/logic/catalog') rememberContract(decoded, response, receivedAt);
    if (path === '/sysinfo' && response.ok) rememberSampling(data);
    if (meta) setServerClock(meta.server_time, sentAt, receivedAt);
    if (!response.ok) throw Object.assign(new Error(errorMessage(payload.error || data?.error || data?.detail || data?.result?.error, `HTTP ${response.status}`)), { data, meta, operation, status: response.status });
    return { ...decoded, status: response.status, sent_at: sentAt, received_at: receivedAt };
  } finally { clearTimeout(timer); }
}
// One flight per poller, bounded timeout, bounded backoff, hidden tabs sleep.
export function poll(load, { interval = 2000, profile = null, onError = () => {}, onVisibility = () => {} } = {}) {
  let timer, busy = false, stopped = false, failures = 0;
  const schedule = () => {
    clearTimeout(timer);
    if (!stopped && !document.hidden) {
      const period = Math.min(30000, (panelIntervals[profile] || interval) * 2 ** failures);
      // Stable profile beats let widgets share reads; groups spread expensive work.
      const delay = failures || !profile ? period
        : period - ((Date.now() - (phases[profile] || 0)) % period + period) % period;
      timer = setTimeout(run, delay);
    }
  };
  async function run() {
    if (busy || stopped || document.hidden) return;
    busy = true;
    try { await load(); failures = 0; }
    catch (error) { failures = Math.min(4, failures + 1); onError(error); }
    finally { busy = false; schedule(); }
  }
  function visibility() {
    clearTimeout(timer);
    onVisibility(document.hidden);
    if (!document.hidden) void run();
  }
  document.addEventListener('visibilitychange', visibility);
  void run();
  return { refresh: run, stop() { stopped = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visibility); } };
}
export function events(onEvent, onError = () => {}) {
  let stream, timer, stopped = false, failures = 0;
  function close() { stream?.close(); stream = null; clearTimeout(timer); }
  function open() {
    close();
    if (stopped || document.hidden || typeof EventSource === 'undefined') return;
    stream = new EventSource('/events');
    stream.onmessage = event => {
      try { const value = JSON.parse(event.data); onEvent(value); failures = 0; }
      catch (error) { onError(error); }
    };
    stream.onerror = () => {
      close(); onError(new Error('SSE disconnected'));
      timer = setTimeout(open, Math.min(30000, 2000 * 2 ** Math.min(failures++, 4)));
    };
  }
  function visibility() { document.hidden ? close() : open(); }
  document.addEventListener('visibilitychange', visibility);
  open();
  return () => { stopped = true; close(); document.removeEventListener('visibilitychange', visibility); };
}
