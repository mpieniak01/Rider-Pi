import { API_ACCEPT, decodeResponse, errorMessage, responseFamily } from './contract.js';
import { setServerClock } from './model.js';
const reads = new Map();
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
export async function prepareMutation() {
  const age = Date.now() / 1000 - (contractProof?.receivedAt ?? 0);
  if (!contractProof || age < 0 || age > 5) await request('/api/logic/catalog');
  if (!contractProof) throw Object.assign(new Error('Unsupported Rider contract; read only'), { status: 409 });
}
export function request(path, options = {}) {
  const method = options.method || 'GET';
  if (method === 'GET' && reads.has(path)) return reads.get(path);
  const flight = performRequest(path, options);
  if (method === 'GET') {
    reads.set(path, flight);
    flight.then(() => reads.delete(path), () => reads.delete(path));
  }
  return flight;
}
async function performRequest(path, { method = 'GET', body, timeout = 6000, beforeSend = () => {} } = {}) {
  const stop = path === '/api/control' && body?.action === 'stop'
    || path === '/api/safety' && ['disarm', 'estop'].includes(body?.action);
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !stop) {
    await prepareMutation();
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
    if (decoded.canonical) {
      const mime = (response.headers?.get?.('content-type') || '').toLowerCase();
      if (mime.split(';')[0].trim() !== 'application/vnd.rider.api+json'
        || !/;\s*version\s*=\s*(?:1|"1")\s*(?:;|$)/.test(mime)) {
        if (path === '/api/logic/catalog') contractProof = null;
        throw Object.assign(new Error('Unsupported Rider response Content-Type; read only'), { status: 502 });
      }
    }
    const receivedAt = Date.now() / 1000;
    if (path === '/api/logic/catalog') rememberContract(decoded, response, receivedAt);
    if (meta) setServerClock(meta.server_time, sentAt, receivedAt);
    if (!response.ok) throw Object.assign(new Error(errorMessage(payload.error || data?.error || data?.detail || data?.result?.error, `HTTP ${response.status}`)), { data, meta, operation, status: response.status });
    return { ...decoded, status: response.status, sent_at: sentAt, received_at: receivedAt };
  } finally { clearTimeout(timer); }
}
// One flight per poller, bounded timeout, bounded backoff, hidden tabs sleep.
export function poll(load, { interval = 2000, onError = () => {}, onVisibility = () => {} } = {}) {
  let timer, busy = false, stopped = false, failures = 0;
  const schedule = () => {
    clearTimeout(timer);
    if (!stopped && !document.hidden) timer = setTimeout(run, Math.min(30000, interval * 2 ** failures));
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
    if (!document.hidden) run();
  }
  document.addEventListener('visibilitychange', visibility);
  run();
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
