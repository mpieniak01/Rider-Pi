// One HTTP decoder for every operator screen. No timestamps are synthesized.
export const API_ACCEPT = 'application/vnd.rider.api+json;version=1';
const versions = Object.fromEntries(['safety', 'telemetry', 'system', 'health', 'resources', 'frames', 'obstacle',
  'navigation', 'odometry', 'calibration', 'providers', 'models', 'voice', 'chat', 'face', 'google_feed', 'home',
  'api_metrics', 'version', 'network', 'mcp', 'project', 'knowledge', 'assistant', 'http'].map(name => ['rider.' + name, 1]));
Object.assign(versions, { 'rider.catalog': 2, 'rider.tasks': 2, 'rider.services': 2, 'rider.service_graph': 2 });
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export function errorMessage(error, fallback = 'Request failed') {
  return typeof error === 'string' ? error : object(error) ? error.message || error.code || fallback : fallback;
}
export function responseFamily(path) {
  const clean = String(path).split('?')[0];
  for (const [prefixes, name] of [
    [['/api/control', '/api/safety', '/api/motion', '/api/flags', '/api/stop', '/api/cmd'], 'safety'],
    [['/api/calibration'], 'calibration'], [['/api/odometry'], 'odometry'], [['/api/navigator'], 'navigation'],
    [['/api/logic/catalog'], 'catalog'], [['/api/logic/'], 'tasks'],
    [['/api/services/graph'], 'service_graph'], [['/svc', '/api/services'], 'services'],
    [['/api/resource'], 'resources'], [['/vision/obstacle', '/api/vision/obstacle'], 'obstacle'],
    [['/vision/tracking/', '/api/vision/tracking/', '/vision/follow/', '/api/vision/follow/'], 'tasks'],
    [['/vision/', '/api/vision/', '/camera/', '/api/last_frame'], 'frames'],
    [['/sysinfo', '/api/metrics', '/api/status'], 'system'],
    [['/health', '/livez', '/readyz', '/api/bus/health'], 'health'],
    [['/api/app-metrics'], 'api_metrics'], [['/api/providers', '/api/system/ai-mode'], 'providers'],
    [['/api/models'], 'models'], [['/api/voice'], 'voice'], [['/api/chat'], 'chat'],
    [['/face/', '/api/draw/face', '/draw/face'], 'face'], [['/api/home'], 'home'],
    [['/api/google', '/raw/last.json'], 'google_feed'], [['/state', '/api/devices'], 'telemetry'],
  ]) if (prefixes.some(prefix => clean.startsWith(prefix))) {
    if (clean === '/api/status/version') return 'rider.version';
    return 'rider.' + name;
  }
  return null;
}
export function decodeResponse(payload, status = 200, expectedFamily = null) {
  if (!object(payload)) return { data: payload, meta: null, operation: null, canonical: false };
  if (!Object.hasOwn(payload, 'meta')) {
    return { data: { ...payload, contract_compatibility: 'legacy_read_only' }, meta: null, operation: null, canonical: false };
  }
  const meta = payload.meta;
  if (!object(meta) || meta.envelope_version !== 1 || typeof meta.contract_id !== 'string'
    || !Object.hasOwn(versions, meta.contract_id) || !Number.isInteger(meta.contract_version)
    || meta.contract_version !== versions[meta.contract_id]
    || expectedFamily && meta.contract_id !== expectedFamily && !(status >= 400 && meta.contract_id === 'rider.http')
    || !Object.hasOwn(payload, 'data') || typeof payload.ok !== 'boolean') {
    throw Object.assign(new Error('Unsupported or invalid Rider response contract'), { status, data: payload });
  }
  // Keep the full source metadata available to renderers and diagnostics. The
  // payload remains in one place; command bodies are never passed through here.
  const data = object(payload.data) ? { ...payload.data, meta,
    ok: payload.ok, operation: payload.operation ?? null } : payload.data;
  if (object(data)) {
    if (!Object.hasOwn(data, 'server_time')) data.server_time = meta.server_time;
    for (const key of ['offline', 'stale']) if (meta[key] === true) data[key] = true;
    if (payload.error !== null && payload.error !== undefined) data.error = payload.error;
  }
  return { data, meta, operation: payload.operation ?? null, canonical: true };
}
