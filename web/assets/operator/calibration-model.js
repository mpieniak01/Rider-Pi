// Pure calibration presentation rules; no transport, clock synchronization or actuation.
import { observationChannel } from './observations.js';
export const COMMAND_MAPPING = 'rider-1.4.2-levels-v3';
export const MAX_PROFILE_BYTES = 65536;
export const digestValid = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const finite = value => typeof value === 'number' && Number.isFinite(value);
const object = value => value && typeof value === 'object' && !Array.isArray(value);
export function freshCalibration(row, now, maxAge = 3) {
  return object(row) && finite(row.observed_at) && row.observed_at > 0
    && row.observed_at <= now && now - row.observed_at <= maxAge
    && row.stale !== true && row.offline !== true;
}
export function defaultProfile(dynamics = {}) {
  const value = (key, fallback) => finite(dynamics[key]) && dynamics[key] > 0 ? dynamics[key] : fallback;
  return { schema_version: 1, name: '', provenance: { kind: 'draft', notes: '' },
    motion: { speed_limit: value('speed_limit', .6), linear_rate: value('linear_rate', 3), turn_rate: value('turn_rate', 4) },
    interaction: { linear_speed: .2, turn_speed: .35, pulse_duration: .25 },
    odometry: { schema_version: 1, manual_verified: false, measurement_id: '', imu_yaw_sign: null,
      conditions: { firmware: '', surface: '', load: '', battery: '', power_cable: '', operator: '', date: '', commit: '', command_mapping: COMMAND_MAPPING },
      linear_m_s: {}, turn_rad_s: {}, observations: Object.fromEntries([
        'minimum_steps', 'acceleration', 'deceleration', 'reversal', 'stop_distance', 'stop_delay',
        'position_error', 'heading_error', 'battery_policy', 'tilt_policy'].map(key => [key, null])) }, measurements: [] };
}
export function measuredTable(rows, maxStep) {
  const table = {};
  for (const row of rows) {
    if (String(row.step).trim() === '' || String(row.rate).trim() === '') throw new Error('measurement_value_required');
    const step = Number(row.step), rate = Number(row.rate);
    if (!Number.isInteger(step) || step === 0 || Math.abs(step) > maxStep || (maxStep === 180 && Math.abs(step) < 1)
      || !finite(rate) || rate * step <= 0 || Object.hasOwn(table, String(step))) throw new Error('invalid_or_duplicate_signed_measurement');
    table[String(step)] = rate;
  }
  return table;
}
function measurementTablesError(odometry) {
  for (const [name, maxStep] of [['linear_m_s', 127], ['turn_rad_s', 180]]) {
    const table = odometry[name];
    if (!object(table) || Object.keys(table).length > 2 * maxStep) return 'invalid_measurement_table';
    for (const [key, value] of Object.entries(table)) {
      const step = Number(key);
      if (!Number.isInteger(step) || String(step) !== key || step === 0 || Math.abs(step) > maxStep || (maxStep === 180 && Math.abs(step) < 1)
        || !finite(value) || value * step <= 0) return 'invalid_signed_measurement';
    }
  }
  return null;
}
function manualEvidenceError(profile) {
  const odom = profile.odometry, conditions = odom.conditions;
  if (profile.provenance.kind !== 'manual' || !profile.provenance.notes.trim()
    || typeof odom.measurement_id !== 'string' || !odom.measurement_id.trim()
    || ![-1, 1].includes(odom.imu_yaw_sign)
    || !object(conditions) || !['firmware', 'surface', 'load', 'battery', 'operator', 'date']
      .every(key => typeof conditions[key] === 'string' && conditions[key].trim())
    || !Object.keys(odom.linear_m_s).length || !Object.keys(odom.turn_rad_s).length
    || !profile.measurements.some(row => row.measurement_id === odom.measurement_id
      && typeof row.notes === 'string' && row.notes.trim())) return 'manual_measurement_evidence_required';
  return null;
}
function motionDynamicsValid(motion) {
  return object(motion) && ['speed_limit', 'linear_rate', 'turn_rate'].every(key => finite(motion[key])
    && motion[key] > 0 && motion[key] <= (key === 'speed_limit' ? 1 : 100));
}
export function profileError(profile) {
  if (!object(profile) || profile.schema_version !== 1 || typeof profile.name !== 'string'
    || !profile.name.trim() || profile.name.length > 80) return 'profile_name_required';
  if (!object(profile.provenance) || !['draft', 'historical', 'manual'].includes(profile.provenance.kind)
    || typeof profile.provenance.notes !== 'string' || profile.provenance.notes.length > 4096) return 'invalid_provenance';
  if (!motionDynamicsValid(profile.motion)) return 'invalid_motion_dynamics';
  if (profile.interaction !== undefined && !interactionValid(profile.interaction)) return 'invalid_interaction_settings';
  if (!object(profile.odometry) || profile.odometry.schema_version !== 1
    || typeof profile.odometry.manual_verified !== 'boolean') return 'invalid_odometry_record';
  const tableError = measurementTablesError(profile.odometry);
  if (tableError) return tableError;
  if (!object(profile.odometry.observations) || !object(profile.odometry.conditions)) return 'invalid_observations_or_conditions';
  if (!Array.isArray(profile.measurements) || profile.measurements.length > 128
    || profile.measurements.some(row => !object(row))) return 'invalid_trial_records';
  if (profile.odometry.manual_verified) return manualEvidenceError(profile);
  return null;
}
export function importedProfile(source) {
  const value = structuredClone(source?.profile || source);
  if (!object(value)) throw new Error('invalid_profile_object');
  value.provenance = { kind: 'historical', notes: typeof value.provenance?.notes === 'string' ? value.provenance.notes : '' };
  if (!object(value.odometry)) throw new Error('invalid_odometry_record');
  value.odometry.manual_verified = false;
  const error = profileError(value); if (error) throw new Error(error);
  return value;
}
export function parseImportedProfile(source) {
  if (typeof source !== 'string' || new TextEncoder().encode(source).length > MAX_PROFILE_BYTES) throw new Error('profile_too_large');
  return importedProfile(JSON.parse(source));
}
export function trialAverage(row) {
  if (!object(row) || !finite(row.duration_s) || row.duration_s <= 0) return null;
  const value = row.kind === 'linear' ? row.distance_m : row.kind === 'turn' ? row.angle_rad : null;
  return finite(value) ? value / row.duration_s : null;
}
export function activationAllowed(state, safety, clockFresh, now) {
  return state?.schema_version === 1 && state.actuation === false && state.stale !== true
    && freshCalibration(state.motion, now) && freshCalibration(state.odometry, now)
    && safety?.contract_version === 1 && freshCalibration(safety, now) && safety.state === 'DISARMED'
    && typeof safety.generation === 'string' && safety.generation.length > 0 && clockFresh === true
    && state.motion.generation === safety.generation && state.motion.moving === false
    && ['target', 'output'].every(name => object(state.motion[name])
      && ['lx', 'az'].every(key => finite(state.motion[name][key]) && state.motion[name][key] === 0));
}
export function activationView(state, expectedDigest = null, now = Date.now() / 1000) {
  const active = state?.active, wanted = expectedDigest || state?.requested?.profile_digest || active?.profile_digest;
  const motion = state?.motion?.calibration, odom = state?.odometry?.calibration;
  const current = state?.schema_version === 1 && state.actuation === false && state.stale !== true && !state.error
    && freshCalibration(state.motion, now) && freshCalibration(state.odometry, now) && freshCalibration(motion, now) && freshCalibration(odom, now);
  const same = digestValid(wanted) && active?.profile_digest === wanted && motion?.profile_digest === wanted
    && odom?.profile_digest === wanted && typeof motion.instance_id === 'string' && Boolean(motion.instance_id)
    && odom.motion_instance_id === motion.instance_id && !motion.error && !odom.error;
  const boot = state?.confirmation === 'loaded_from_saved' && motion?.source === 'saved_profile'
    && odom?.source === 'saved_profile' && !motion.applied_ack && !motion.applied_generation && !odom.applied_generation && !motion.activation_request_id && !odom.activation_request_id;
  const ack = motion?.applied_ack;
  const executed = state?.confirmation === 'executed' && ack?.status === 'executed'
    && ack.accepted === true && ack.actuation === false && !ack.error && ack.action === 'activate_calibration' && ack.source === 'manual' && ack.profile_digest === wanted
    && typeof active?.request_id === 'string' && Boolean(active.request_id) && ack.request_id === active.request_id
    && motion.activation_request_id === active.request_id && odom.activation_request_id === active.request_id && Number.isInteger(active.seq) && active.seq >= 0
    && ack.seq === active.seq && odom.seq === active.seq
    && typeof active.command_generation === 'string' && Boolean(active.command_generation)
    && (ack.command_generation ?? ack.generation) === active.command_generation
    && motion.command_generation === active.command_generation && odom.command_generation === active.command_generation
    && typeof motion.applied_generation === 'string' && Boolean(motion.applied_generation)
    && odom.applied_generation === motion.applied_generation && ack.generation === motion.applied_generation
    && ack.instance_id === state.motion.instance_id && motion.instance_id === state.motion.instance_id
    && finite(ack.observed_at) && finite(active.activated_at) && active.activated_at <= ack.observed_at && ack.observed_at <= now;
  const applied = Boolean(current && same && active?.activation_state === 'applied' && state.status === 'applied' && (boot || executed));
  return { applied, status: applied ? 'applied' : state?.stale === true || !freshCalibration(state?.motion, now) ? 'unknown' : state?.status === 'partial' ? 'partial' : 'pending',
    digest: wanted || null, confirmation: applied ? state.confirmation : 'unconfirmed',
    recordVerified: applied && odom?.record_verified === true,
    modelReady: applied && state.model_ready === true && odom?.model_ready === true,
    modelError: state?.calibration_error || odom?.odometry_error || motion?.odometry_error || null };
}
export function pulseValues(vx, yaw, duration) {
  if ([vx, yaw, duration].some(value => String(value).trim() === '')) throw new Error('pulse_value_required');
  const values = { vx: Number(vx), yaw: Number(yaw), duration: Number(duration) };
  if (!Object.values(values).every(finite) || Math.abs(values.vx) > 1 || Math.abs(values.yaw) > 1
    || values.duration < .01 || values.duration > .25 || (values.vx === 0 && values.yaw === 0)) throw new Error('invalid_single_pulse');
  return values;
}

export function referenceConfirmed(snapshot, command, now) {
  const ack = snapshot?.last_ack;
  return snapshot?.contract_version === 1 && freshCalibration(snapshot, now) && !snapshot.error
    && snapshot.actuation === false && snapshot.reference_verified === true && snapshot.reference_id === command.request_id
    && ack?.status === 'executed' && ack.accepted === true && ack.action === 'reference' && ack.actuation === false
    && ack.request_id === command.request_id && ack.source === command.source && ack.seq === command.seq
    && (!command.profile_digest || (snapshot.calibration?.profile_digest === command.profile_digest
      && snapshot.pose?.calibration_id === command.profile_digest && ack.profile_digest === command.profile_digest))
    && ack.command_generation === command.generation && ack.instance_id === snapshot.instance_id
    && finite(ack.observed_at) && ack.observed_at >= command.ts
    && (!command.home_operator_confirmed || (snapshot.home?.operator_confirmed === true
      && snapshot.home.reference_id === command.request_id && snapshot.home.x === command.home_x
      && snapshot.home.y === command.home_y));
}

export function activationPendingResult(state, command, now) {
  const fresh = freshCalibration(state?.motion, now) && freshCalibration(state?.odometry, now) && state?.stale !== true;
  if (!fresh) return now - command.ts > 8 ? { status: 'unknown', reason: 'activation_confirmation_timeout_no_retry' } : null;
  const active = state.active, requested = state.requested;
  if (activationView(state, command.profile_digest, now).applied && active?.request_id === command.request_id
    && active.command_generation === command.generation && active.seq === command.seq) return { status: 'applied', reason: null };
  if (requested?.request_id === command.request_id && requested.profile_digest === command.profile_digest
    && requested.generation === command.generation && requested.seq === command.seq && requested.source === command.source
    && state.status === 'partial' && typeof state.error === 'string' && state.error) return { status: 'partial', reason: state.error };
  return now - command.ts > 8 ? { status: 'unknown', reason: 'activation_confirmation_timeout_no_retry' } : null;
}

// Status publication time never replaces original SDK/sensor observations.
function motionParent(motion, now) {
  const identity = motion?.contract_version === 1 && motion.uart_owner === 'motion-executor'
    && typeof motion.instance_id === 'string' && Boolean(motion.instance_id)
    && typeof motion.generation === 'string' && Boolean(motion.generation);
  const error = typeof motion?.error === 'string' && motion.error.startsWith('sensor_quality:') ? null : motion?.error;
  return Boolean(identity && freshCalibration(motion, now) && motion.hardware_ready === true
    && !error && !motion.data_error);
}
function sourceAge(row, now) {
  return finite(row?.observed_at) && row.observed_at > 0 && row.observed_at <= now ? now - row.observed_at : null;
}
export function sdkOutputObservation(motion, now) {
  const row = motion?.sdk_output, age = sourceAge(row, now);
  const steps = object(row) && Number.isInteger(row.linear_step) && Math.abs(row.linear_step) <= 127
    && Number.isInteger(row.turn_step) && (row.turn_step === 0 || (Math.abs(row.turn_step) >= 1 && Math.abs(row.turn_step) <= 180))
    && typeof row.stopped === 'boolean' && (!row.stopped || (row.linear_step === 0 && row.turn_step === 0));
  const trusted = Boolean(motionParent(motion, now) && steps && row.source === 'motion-executor' && row.accepted === true
    && row.instance_id === motion.instance_id && row.generation === motion.generation
    && row.stale !== true && row.offline !== true && !row.error && !row.data_error && age !== null);
  const ready = trusted && age <= .25;
  return { ready, status: ready ? 'observed' : trusted ? 'stale' : 'unknown', age_s: age,
    linear_step: trusted ? row.linear_step : null, turn_step: trusted ? row.turn_step : null,
    accepted: row?.accepted === true, source: row?.source ?? null, observed_at: row?.observed_at ?? null,
    instance_id: row?.instance_id ?? null, generation: row?.generation ?? null,
    error: ready ? null : trusted ? 'sdk_output_stale' : row?.error || 'sdk_output_unconfirmed',
    physical_completion: 'unverified' };
}
export function sensorObservations(motion, now) {
  return Object.fromEntries(['roll', 'pitch', 'yaw', 'battery'].map(name =>
    [name, observationChannel(motion, name, { now, requireMotion: true })]));
}
export function currentDynamics(motion, now) {
  const row = motion?.dynamics;
  const ready = motion?.contract_version === 1 && freshCalibration(motion, now)
    && motion.uart_owner === 'motion-executor' && typeof motion.instance_id === 'string' && Boolean(motion.instance_id)
    && typeof motion.generation === 'string' && Boolean(motion.generation) && !motion.calibration?.error
    && object(row) && row.ready === true && !row.error
    && ['speed_limit', 'linear_rate', 'turn_rate'].every(key => finite(row[key])
      && row[key] > 0 && row[key] <= (key === 'speed_limit' ? 1 : 100));
  return { ready: Boolean(ready), observed_at: motion?.observed_at ?? null, age_s: sourceAge(motion, now),
    speed_limit: ready ? row.speed_limit : null, linear_rate: ready ? row.linear_rate : null,
    turn_rate: ready ? row.turn_rate : null, error: ready ? null : row?.error || 'motion_dynamics_unconfirmed',
    physical_completion: 'unverified' };
}

export function interactionValid(row) {
  return object(row) && ['linear_speed', 'turn_speed'].every(key => finite(row[key]) && row[key] >= 0 && row[key] <= 1)
    && finite(row.pulse_duration) && row.pulse_duration >= .01 && row.pulse_duration <= .25;
}
export function interactionSettings(row) {
  return interactionValid(row) ? { ...row } : { linear_speed: .2, turn_speed: .35, pulse_duration: .25 };
}
