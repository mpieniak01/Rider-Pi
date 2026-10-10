// Pure contract rules shared by rendering and isolated fixture tests.
let serverUpperOffset = 0, serverLowerOffset = 0;
// Observation age uses the older/conservative bound; commands use the bound
// that cannot be in the server's future even with asymmetric network latency.
export const nowSeconds = () => Date.now() / 1000 + serverUpperOffset;
export const commandSeconds = () => Date.now() / 1000 + serverLowerOffset;
export function setServerClock(serverTime, sentAt, receivedAt) {
  if (![serverTime, sentAt, receivedAt].every(value => typeof value === 'number' && Number.isFinite(value))
    || serverTime <= 0 || receivedAt < sentAt || receivedAt - sentAt > .5) return false;
  serverUpperOffset = serverTime - sentAt;
  serverLowerOffset = serverTime - receivedAt;
  return true;
}
export function ageOf(row, now = nowSeconds()) {
  const ts = row && Object.hasOwn(row, 'observed_at') ? row.observed_at : row?.ts;
  return typeof ts === 'number' && Number.isFinite(ts) && ts > 0 && ts <= now + .1
    ? Math.max(0, now - ts) : null;
}
export function fresh(row, seconds = 3, now = nowSeconds()) {
  const age = ageOf(row, now);
  return row?.stale !== true && age !== null && age <= seconds;
}
// Measurement usability is distinct from the freshness of a task status.
function measurementAvailable(row) {
  const quality = typeof row?.quality === 'string' ? row.quality.toLowerCase() : row?.quality;
  return row?.stale !== true && row?.offline !== true && !row?.error && !row?.data_error
    && row?.data_ready !== false && row?.navigation_ready !== false
    && quality !== null && !['unknown', 'unavailable', 'invalid', 'error', 'failed'].includes(quality);
}
export function presentationReady(row, seconds = 3, now = nowSeconds()) {
  return fresh(row, seconds, now) && measurementAvailable(row);
}
export function navigationObservation(data, previous = null, now = nowSeconds()) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return { observed_at: null, ts: null, stale: true, data_ready: false, error: 'navigation_data_unknown' };
  }
  const ts = Object.hasOwn(data, 'observed_at') ? data.observed_at : data.ts;
  if (ageOf({ observed_at: ts }, now) === null) {
    return { observed_at: null, ts: null, stale: true, data_ready: false,
      offline: data.offline === true, error: data.error || 'navigation_observation_time_unknown',
      quality: data.quality ?? 'unknown' };
  }
  // Late healthy samples cannot replace a newer observation. Explicit source
  // failure still expires it, including an error carrying an older timestamp.
  if (typeof previous?.observed_at === 'number' && ts < previous.observed_at && measurementAvailable(data)) return previous;
  return { ...data, observed_at: ts };
}
export function safetyKnown(safety, now = nowSeconds()) {
  return safety?.contract_version === 1 && fresh(safety, 3, now)
    && ['DISARMED', 'ARMED', 'ESTOP'].includes(safety.state)
    && typeof safety.generation === 'string' && Boolean(safety.generation);
}
export function authorized(safety, owner, action = 'move', now = nowSeconds()) {
  const capability = safety?.capabilities?.[action];
  const age = ageOf(safety, now);
  return safetyKnown(safety, now) && safety.state === 'ARMED'
    && safety.ready === true && safety.hardware_ready === true && safety.can_move === true && safety.read_only === false && safety.owner === owner
    && Number.isFinite(safety.lease_remaining_s) && safety.lease_remaining_s > age && safety.lease_remaining_s <= 30
    && capability?.available === true && capability.stop_verified === true;
}
export function catalogKnown(catalog, now = nowSeconds()) {
  return catalog?.contract_version === 2 && catalog?.catalog_version === 2
    && catalog.offline !== true && !catalog.error
    && Array.isArray(catalog.features) && Array.isArray(catalog.units)
    && fresh(catalog, 10, now);
}
export function taskCanStart(task, catalog, safety, now = nowSeconds()) {
  return catalogKnown(catalog, now) && task?.installed === true && typeof task.can_move === 'boolean' && fresh(task, 10, now)
    && !['starting', 'stopping'].includes(task.state)
    && (!task.can_move || (authorized(safety, task.motion_owner, 'move', now)
      && authorized(safety, task.motion_owner, 'turn', now)));
}
export function editingTarget(target) {
  return Boolean(target?.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"]'));
}
export function matchingAck(ack, command, submittedAt, confirmedHttp = false) {
  return ack?.request_id === command.request_id && ack?.action === command.action
    && ack?.source === command.source && (ack?.seq ?? null) === (command.seq ?? null)
    && (!command.generation || (ack?.command_generation ?? ack?.generation) === command.generation)
    && typeof ack.observed_at === 'number' && Number.isFinite(ack.observed_at)
    && (confirmedHttp || ack.observed_at >= submittedAt)
    && ['executed', 'rejected'].includes(ack.status);
}
export function displayValue(value, suffix = '') {
  return value === null || value === undefined ? '—' : `${value}${suffix}`;
}
export function cameraFrame(meta, kind, now = nowSeconds()) {
  const row = meta?.[kind];
  const ts = row && Object.hasOwn(row, 'observed_at') ? row.observed_at : row?.mtime;
  const age = ageOf({ observed_at: ts }, now);
  return { exists: row?.exists === true, ts, age,
    fresh: meta?.offline !== true && meta?.stale !== true && !meta?.error && row?.stale !== true
      && row?.exists === true && age !== null && age <= 3 };
}
export function gridPoint(map, point) {
  const x = Array.isArray(point) ? point[0] : point?.x, y = Array.isArray(point) ? point[1] : point?.y;
  const resolution = map?.resolution_m, ox = map?.origin_x, oy = map?.origin_y;
  if (![x, y, resolution, ox, oy].every(value => typeof value === 'number' && Number.isFinite(value)) || resolution <= 0) return null;
  // Mapper origin is an additive offset, as in navigator.world_to_grid.
  const coords = [(x + ox) / resolution, (y + oy) / resolution];
  return coords.every(Number.isFinite) ? coords : null;
}
