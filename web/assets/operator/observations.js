// Pure measurement presentation shared by Overview, Devices and Calibration.
// Known legacy formats are explicit adapters; values never identify their units.
const finite = value => typeof value === 'number' && Number.isFinite(value);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const sourceAge = (at, now) => finite(at) && at > 0 && at <= now + .1 ? Math.max(0, now - at) : null;

function legacyUnit(name,canonical) {
  if(canonical)return null;
  return name === 'battery' ? 'ratio' : 'sdk_raw';
}
function legacyValue(parent,name) {
  if(name === 'battery')return finite(parent?.battery_pct) ? parent.battery_pct / 100 : null;
  if(name === 'yaw')return Object.hasOwn(parent || {},'yaw_raw') ? parent.yaw_raw : null;
  return parent?.[name];
}
function measuredValue(parent,row,name,canonical,requireMotion) {
  if(row && Object.hasOwn(row,'value')) {
    // Safety-v1 already defined ratio battery and raw SDK axes.
    const unit=Object.hasOwn(row,'unit') ? row.unit : legacyUnit(name,canonical);
    return {value:row.value,unit};
  }
  if(canonical || requireMotion)return {value:null,unit:null};
  return {value:legacyValue(parent,name),unit:legacyUnit(name,false)};
}
function measuredAt(parent,row,name,canonical,requireMotion) {
  if (row && Object.hasOwn(row,'observed_at')) return row.observed_at;
  if (canonical || requireMotion) return null;
  const times=parent?.sensor_observed_at || {};
  if (Object.hasOwn(times,name)) return times[name];
  if (name === 'battery' && Object.hasOwn(parent || {},'battery_observed_at')) return parent.battery_observed_at;
  return Object.hasOwn(parent || {},'observed_at') ? parent.observed_at : parent?.ts;
}
function measuredAge(parent,row,observedAt,now,requireMotion) {
  let age=sourceAge(observedAt,now);
  if (requireMotion && observedAt > now) age=null;
  // Pair age with its explicit assessment, never producer publication time.
  const assessed=row && Object.hasOwn(row,'assessed_at') ? row.assessed_at : requireMotion ? parent?.observed_at : null;
  const published=sourceAge(assessed,now);
  if (finite(row?.age_s) && row.age_s >= 0 && published !== null && age !== null) age=Math.max(age,row.age_s+published);
  if (requireMotion && (!finite(row?.age_s) || row.age_s < 0)) age=null;
  return age;
}
function motionIdentity(parent,row,now,requireMotion) {
  return !requireMotion || parent?.contract_version === 1 && parent.uart_owner === 'motion-executor'
    && typeof parent.instance_id === 'string' && Boolean(parent.instance_id)
    && typeof parent.generation === 'string' && Boolean(parent.generation)
    && sourceAge(parent.observed_at,now) !== null && sourceAge(parent.observed_at,now) <= 3
    && parent.hardware_ready === true
    && (!row?.instance_id || row.instance_id === parent.instance_id)
    && (!row?.generation || row.generation === parent.generation);
}
function expectedUnit(name) {
  if (name === 'battery') return 'ratio';
  if (name === 'work_status') return 'code';
  return ['accel_x','accel_y','accel_z'].includes(name) ? 'm/s^2' : 'sdk_raw';
}
function valueValid(value,unit,expected,name) {
  return finite(value) && unit === expected
    && (name !== 'work_status' || Number.isInteger(value) && [0,1].includes(value))
    && (name !== 'battery' || value >= 0 && value <= 1);
}
function channelState(parent,row,name,age,maxAge,identity,validValue,unavailable) {
  const parentError=typeof parent?.error === 'string' && parent.error.startsWith('sensor_quality:') ? null : parent?.error;
  const error=row?.error || row?.data_error || parentError || parent?.data_error || null;
  const offline=unavailable || parent?.offline === true || row?.offline === true || parent?.meta?.offline === true;
  const stale=parent?.stale === true || parent?.meta?.stale === true || row?.stale === true || age === null || age > maxAge;
  const ready=Boolean(validValue && identity && !offline && !error && parent?.simulated !== true && row?.simulated !== true
    && (!row || row.ready === true) && !stale && (name !== 'battery' || parent?.battery_ok !== false));
  return {error,offline,stale,ready};
}
function channelStatus(ready,age,maxAge) {
  if (ready) return 'observed';
  return age !== null && age > maxAge ? 'stale' : 'unknown';
}
function displayedValue(ready,name,value) {
  if (!ready) return null;
  return name === 'battery' ? value*100 : value;
}
function channelError(ready,error,identity) {
  if (ready) return null;
  return error || (!identity ? 'motion_parent_unconfirmed' : 'measurement_stale_or_missing');
}
export function observationChannel(input,name,{now=Date.now()/1000,unavailable=false,requireMotion=false}={}) {
  const parent=object(input?.observation) ? input.observation : input;
  const canonical=parent?.contract_id === 'rider.telemetry' && parent.contract_version === 1;
  const sensors=parent?.sensor_quality?.sensors || parent?.sensor_quality || {};
  const row=object(sensors[name]) ? sensors[name] : null;
  const {value,unit}=measuredValue(parent,row,name,canonical,requireMotion);
  const observedAt=measuredAt(parent,row,name,canonical,requireMotion);
  const age=measuredAge(parent,row,observedAt,now,requireMotion);
  const maxAge=Math.min(2.5,finite(row?.max_age_s) && row.max_age_s > 0 ? row.max_age_s : 2.5);
  const identity=motionIdentity(parent,row,now,requireMotion), expected=expectedUnit(name);
  const state=channelState(parent,row,name,age,maxAge,identity,valueValid(value,unit,expected,name),unavailable);
  return {...row,observed_at:observedAt ?? null,age_s:age,offline:state.offline,stale:state.stale,
    ready:state.ready,producer_ready:row?.ready === true,status:channelStatus(state.ready,age,maxAge),
    value:displayedValue(state.ready,name,value),raw_value:value,raw_unit:unit,unit:name === 'battery' ? '%' : expected,
    source:row?.source || parent?.source || 'unknown',error:channelError(state.ready,state.error,identity),
    physical_validity:'unverified',physical_completion:'unverified'};
}
