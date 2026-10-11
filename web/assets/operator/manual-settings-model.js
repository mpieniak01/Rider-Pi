// Pi owns direction mapping, calibration and smoothing.
export const fields = ['linear_speed','turn_speed','pulse_duration','speed_limit','linear_rate','turn_rate',
  'linear_deceleration','turn_deceleration','reversal_pause'];
export const directions = ['forward','backward','left','right'];
export function parameter(row, key) {
  return row?.parameter_schema?.direction_fields?.[key] || row?.parameter_schema?.value_fields?.[key] || null;
}
export function descriptionsValid(row) {
  const schema=row?.parameter_schema, modes=row?.control_modes;
  return schema?.version===1 && modes?.version===1
    && ['speed','minimum','maximum','step','duration'].every(k=>validParameter(schema.direction_fields?.[k]))
    && ['linear_rate','turn_rate','linear_deceleration','turn_deceleration','reversal_pause'].every(k=>validParameter(schema.value_fields?.[k]))
    && ['pulse','hold','release'].every(mode=>modes.supported?.includes(mode))
    && Number.isFinite(modes.hold_renewal_ms) && modes.hold_renewal_ms>0
    && modes.hold_renewal_ms<modes.hold_timeout_ms && modes.hold_timeout_ms<=500
    && Number.isFinite(modes.click_threshold_ms) && modes.click_threshold_ms>0;
}
function validParameter(p) {
  return p?.type==='number' && typeof p.unit==='string' && typeof p.display_unit==='string'
    && Number.isFinite(p.display_factor) && p.display_factor>0
    && Number.isFinite(p.minimum) && Number.isFinite(p.maximum) && p.minimum<=p.maximum
    && Number.isInteger(p.display_precision) && p.display_precision>=0 && p.display_precision<=20;
}
export function displayFactor(row, key) {
  const value=parameter(row,key)?.display_factor;
  if(!Number.isFinite(value) || value<=0)throw new Error('parameter_description_unavailable');
  return value;
}
// All screens use the same device-provided display units and factors.
export function displayValue(row, key, value) {
  return Number.isFinite(value) ? Number((value * displayFactor(row,key)).toPrecision(15)) : NaN;
}
export function formatParameter(row, key, value, lang='pl') {
  if(!Number.isFinite(value) || !parameter(row,key))return '—';
  const p=parameter(row,key), shown=displayValue(row,key,value);
  // Round display labels using Pi's precision; editable values remain unchanged.
  const precision=Number.isInteger(p.display_precision) ? Math.max(0,Math.min(20,p.display_precision)) : 0;
  const number=shown.toLocaleString(lang,{maximumFractionDigits:precision,useGrouping:false});
  return number+(p.display_unit.startsWith('%')?'':' ')+p.display_unit;
}
export function parameterRange(row,key,lang='pl') {
  const p=parameter(row,key);
  if(!p)return '—';
  const number=value=>displayValue(row,key,value).toLocaleString(lang,{maximumFractionDigits:20,useGrouping:false});
  return number(p.minimum)+'–'+number(p.maximum)+' '+p.display_unit;
}
export function settingsValid(row, now) {
  return row?.contract_id === 'rider.manual_settings' && row.contract_version === 2
    && row.schema_version === 2 && row.authority === 'device'
    && Number.isInteger(row.revision) && row.revision >= 0 && row.actuation === false
    && Number.isFinite(row.observed_at) && now >= row.observed_at && now - row.observed_at <= 3
    && fields.every(key => Number.isFinite(row.values?.[key]) && row.values[key] >= 0
      && Number.isFinite(row.limits?.[key]) && row.values[key] <= row.limits[key])
    && directions.every(name => {
      const d=row.directions?.[name];
      return d && ['minimum','maximum','step','speed','duration'].every(k=>Number.isFinite(d[k]))
        && d.minimum>=0 && d.minimum<=d.maximum && d.maximum<=row.values.speed_limit
        && d.speed>=0 && (d.speed===0 || d.speed>=d.minimum) && d.speed<=d.maximum
        && d.step>0 && d.step<=1 && d.duration>=(parameter(row,"duration")?.minimum ?? .01) && d.duration<=(parameter(row,"duration")?.maximum ?? row.limits.pulse_duration);
    });
}
export function settingsPulse(row, direction) {
  if (!directions.includes(direction)) throw new Error('manual_direction');
  return {direction,device_settings:true,settings_revision:row.revision};
}
