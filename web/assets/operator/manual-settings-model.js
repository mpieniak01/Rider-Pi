// Pi owns direction mapping, calibration and smoothing.
export const fields = ['linear_speed','turn_speed','pulse_duration','speed_limit','linear_rate','turn_rate',
  'linear_deceleration','turn_deceleration','reversal_pause'];
export const directions = ['forward','backward','left','right'];
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
        && d.step>0 && d.step<=1 && d.duration>=.01 && d.duration<=1;
    });
}
export function settingsPulse(row, direction) {
  if (!directions.includes(direction)) throw new Error('manual_direction');
  return {direction,device_settings:true,settings_revision:row.revision};
}
