// Pure measurement presentation shared by Overview, Devices and Calibration.
// Known legacy formats are explicit adapters; values never identify their units.
const finite = value => typeof value === 'number' && Number.isFinite(value);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const sourceAge = (at, now) => finite(at) && at > 0 && at <= now + .1 ? Math.max(0, now - at) : null;
export function observationChannel(input, name, { now = Date.now() / 1000, unavailable = false, requireMotion = false } = {}) {
  const parent = object(input?.observation) ? input.observation : input;
  const canonical = parent?.contract_id === 'rider.telemetry' && parent.contract_version === 1;
  const sensors = parent?.sensor_quality?.sensors || parent?.sensor_quality || {};
  const row = object(sensors[name]) ? sensors[name] : null;
  let value, unit;
  if (row && Object.hasOwn(row, 'value')) {
    value = row.value;
    // The safety-v1 channels already defined battery as a ratio and SDK axes
    // as raw values before the HTTP envelope existed.
    unit = Object.hasOwn(row, 'unit') ? row.unit : canonical ? null : name === 'battery' ? 'ratio' : 'sdk_raw';
  } else if (canonical || requireMotion) {
    value = null; unit = null;
  } else if (name === 'battery') {
    value = finite(parent?.battery_pct) ? parent.battery_pct / 100 : null; unit = 'ratio';
  } else {
    value = name === 'yaw' ? Object.hasOwn(parent || {}, 'yaw_raw') ? parent.yaw_raw : null : parent?.[name];
    unit = 'sdk_raw';
  }
  const times = parent?.sensor_observed_at || {};
  const observed_at = row && Object.hasOwn(row, 'observed_at') ? row.observed_at
    : canonical || requireMotion ? null : Object.hasOwn(times, name) ? times[name]
      : name === 'battery' && Object.hasOwn(parent || {}, 'battery_observed_at') ? parent.battery_observed_at
        : Object.hasOwn(parent || {}, 'observed_at') ? parent.observed_at : parent?.ts;
  let age_s = sourceAge(observed_at, now);
  if (requireMotion && observed_at > now) age_s = null;
  // Canonical REST rows may have had age recomputed after producer publication.
  // Only the explicit assessment time (or original safety snapshot assessment)
  // pairs with age_s; producer generated_at cannot be added a second time.
  const assessed = row && Object.hasOwn(row, 'assessed_at') ? row.assessed_at
    : requireMotion ? parent?.observed_at : null;
  const published = sourceAge(assessed, now);
  if (finite(row?.age_s) && row.age_s >= 0 && published !== null && age_s !== null) age_s = Math.max(age_s, row.age_s + published);
  if (requireMotion && (!finite(row?.age_s) || row.age_s < 0)) age_s = null;
  const maxAge = Math.min(2.5, finite(row?.max_age_s) && row.max_age_s > 0 ? row.max_age_s : 2.5);
  const parentError = typeof parent?.error === 'string' && parent.error.startsWith('sensor_quality:') ? null : parent?.error;
  const identity = !requireMotion || parent?.contract_version === 1 && parent.uart_owner === 'motion-executor'
    && typeof parent.instance_id === 'string' && Boolean(parent.instance_id)
    && typeof parent.generation === 'string' && Boolean(parent.generation)
    && sourceAge(parent.observed_at, now) !== null && sourceAge(parent.observed_at, now) <= 3
    && parent.hardware_ready === true
    && (!row?.instance_id || row.instance_id === parent.instance_id)
    && (!row?.generation || row.generation === parent.generation);
  const validValue = finite(value) && unit === (name === 'battery' ? 'ratio' : 'sdk_raw')
    && (name !== 'battery' || value >= 0 && value <= 1);
  const error = row?.error || row?.data_error || parentError || parent?.data_error || null;
  const offline = unavailable || parent?.offline === true || row?.offline === true || parent?.meta?.offline === true;
  const stale = parent?.stale === true || parent?.meta?.stale === true || row?.stale === true || age_s === null || age_s > maxAge;
  const ready = Boolean(validValue && identity && !offline && !error && parent?.simulated !== true && row?.simulated !== true
    && (!row || row.ready === true) && !stale
    && (name !== 'battery' || parent?.battery_ok !== false));
  return { ...row, observed_at: observed_at ?? null, age_s, offline,
    stale,
    ready, producer_ready: row?.ready === true, status: ready ? 'observed' : age_s !== null && age_s > maxAge ? 'stale' : 'unknown',
    value: ready ? name === 'battery' ? value * 100 : value : null,
    raw_value: value, raw_unit: unit, unit: name === 'battery' ? '%' : 'sdk_raw',
    source: row?.source || parent?.source || 'unknown',
    error: ready ? null : error || (!identity ? 'motion_parent_unconfirmed' : 'measurement_stale_or_missing'),
    physical_validity: 'unverified', physical_completion: 'unverified' };
}
