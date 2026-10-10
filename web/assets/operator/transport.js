const reads = new Map();
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
async function performRequest(path, { method = 'GET', body, timeout = 6000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const sentAt = Date.now() / 1000;
  try {
    const response = await fetch(path, { method, cache: 'no-store', signal: controller.signal,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw Object.assign(new Error(data.error || data.detail || data.result?.error || `HTTP ${response.status}`), { data, status: response.status });
    return { data, status: response.status, sent_at: sentAt, received_at: Date.now() / 1000 };
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
