// Read-only presentation of source observations; never changes producer cadence.
const finite = value => typeof value === 'number' && Number.isFinite(value);
function historyClock(system, elapsed, now) {
  const times=Array.isArray(system?.hist_ts)?system.hist_ts:[];
  const observation=system?.observation;
  const monotonic=Array.isArray(system?.hist_mono)&&system.hist_mono.length===times.length
    &&finite(observation?.monotonic_s)&&finite(observation?.age_s);
  const stamps=monotonic?system.hist_mono:times;
  const cadence=finite(system?.sampling?.summary_interval_ms)?system.sampling.summary_interval_ms/1000:1;
  const age=stamp=>monotonic?observation.age_s+Math.max(0,elapsed)+observation.monotonic_s-stamp:now-stamp;
  return {stamps,cadence,age};
}
function separatedSample(system, stamps, i, cadence) {
  if(i===0)return false;
  const previous=stamps[i-1],stamp=stamps[i];
  return !finite(previous)||stamp<=previous||stamp-previous>2*cadence
    ||Array.isArray(system.hist_generation)&&system.hist_generation[i]!==system.hist_generation[i-1]
    ||Array.isArray(system.hist_seq)&&system.hist_seq[i]!==system.hist_seq[i-1]+1;
}
export function systemHistory(system, elapsed = 0, now = Date.now() / 1000) {
  const clock=historyClock(system,elapsed,now),points=[];
  let gaps=false;
  for(let i=0;i<clock.stamps.length;i++){
    const stamp=clock.stamps[i],age=clock.age(stamp);
    if(!finite(stamp)||!finite(age)||age<-.1||age>60)continue;
    const separated=separatedSample(system,clock.stamps,i,clock.cadence);
    gaps ||= separated;
    points.push({age:Math.max(0,age),separated,cpu:system.hist_cpu?.[i],mem:system.hist_mem?.[i],peak:system.hist_cpu_peak?.[i]});
  }
  return {points,gaps,count:points.length,span:points.length?Math.max(0,points[0].age-points.at(-1).age):0};
}

export function systemEvent(previous, next) {
  const a=previous?.observation, b=next?.observation;
  if(!a || !b)return null;
  if(a.boot_id && b.boot_id && a.boot_id!==b.boot_id)return 'hostRestart';
  if(a.instance_id && b.instance_id && a.instance_id!==b.instance_id)return 'apiRestart';
  if(a.instance_id && a.instance_id===b.instance_id && finite(a.generation) && finite(b.generation) && a.generation!==b.generation)return 'samplerResume';
  return null;
}
