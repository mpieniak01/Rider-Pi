// Read-only presentation of source observations; never changes producer cadence.
const finite = value => typeof value === 'number' && Number.isFinite(value);
export function systemHistory(system, elapsed = 0, now = Date.now() / 1000) {
  const times = Array.isArray(system?.hist_ts) ? system.hist_ts : [];
  const mono = system?.hist_mono, generations = system?.hist_generation, seq = system?.hist_seq;
  const observation = system?.observation;
  const monotonic = Array.isArray(mono) && mono.length === times.length
    && finite(observation?.monotonic_s) && finite(observation?.age_s);
  const cadence = finite(system?.sampling?.summary_interval_ms) ? system.sampling.summary_interval_ms / 1000 : 1;
  const points = [];
  let gaps = false;
  for (let i = 0; i < times.length; i++) {
    const stamp = monotonic ? mono[i] : times[i], previous = monotonic ? mono[i - 1] : times[i - 1];
    const age = monotonic ? observation.age_s + Math.max(0, elapsed) + observation.monotonic_s - stamp : now - stamp;
    if (!finite(stamp) || !finite(age) || age < -.1 || age > 60) continue;
    const separated = i > 0 && (!finite(previous) || stamp <= previous || stamp - previous > 2 * cadence
      || Array.isArray(generations) && generations[i] !== generations[i - 1]
      || Array.isArray(seq) && seq[i] !== seq[i - 1] + 1);
    gaps ||= separated;
    points.push({age: Math.max(0, age), separated, cpu: system.hist_cpu?.[i], mem: system.hist_mem?.[i], peak: system.hist_cpu_peak?.[i]});
  }
  return {points, gaps, count: points.length, span: points.length ? Math.max(0, points[0].age - points.at(-1).age) : 0};
}

export function systemEvent(previous, next) {
  const a=previous?.observation, b=next?.observation;
  if(!a || !b)return null;
  if(a.boot_id && b.boot_id && a.boot_id!==b.boot_id)return 'hostRestart';
  if(a.instance_id && b.instance_id && a.instance_id!==b.instance_id)return 'apiRestart';
  if(a.instance_id && a.instance_id===b.instance_id && a.generation!==b.generation)return 'samplerResume';
  return null;
}
