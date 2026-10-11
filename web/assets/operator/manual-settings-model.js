// Shared Pi settings, never inferred from initial HTML values.
export const fields = ['linear_speed','turn_speed','pulse_duration','speed_limit','linear_rate','turn_rate'];
export function settingsValid(row, now) {
  return row?.contract_id === 'rider.manual_settings' && row.contract_version === 1
    && Number.isInteger(row.revision) && row.revision >= 0 && row.actuation === false
    && Number.isFinite(row.observed_at) && now >= row.observed_at && now - row.observed_at <= 3
    && fields.every(key => Number.isFinite(row.values?.[key]) && row.values[key] >= (['linear_speed','turn_speed'].includes(key) ? 0 : key === 'pulse_duration' ? .01 : .001)
      && Number.isFinite(row.limits?.[key]) && row.values[key] <= row.limits[key]);
}
export function settingsPulse(row, direction) {
  const v = row.values;
  const pair = { forward:[v.linear_speed,0], backward:[-v.linear_speed,0], left:[0,-v.turn_speed], right:[0,v.turn_speed] }[direction];
  if (!pair) throw new Error('manual_direction');
  return { direction, vx:pair[0], yaw:pair[1], duration:v.pulse_duration, settings_revision:row.revision };
}
