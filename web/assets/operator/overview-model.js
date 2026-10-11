import { ageOf } from './model.js';
export function telemetrySummary(samples, now) {
  const channels = ['roll', 'pitch', 'yaw', 'battery'].map(name => samples[name]);
  const complete = channels.every(row => row?.ready === true && ageOf(row, now) !== null);
  return { complete, age: complete ? Math.max(...channels.map(row => ageOf(row, now))) : null };
}
// Physical yaw semantics are not established for this firmware. Keep it in diagnostics.
export function orientationSummary(samples) {
  const fmt = sample => sample?.ready && Number.isFinite(sample.value) ? sample.value.toFixed(1) : '—';
  return 'R ' + fmt(samples.roll) + ' · P ' + fmt(samples.pitch);
}
