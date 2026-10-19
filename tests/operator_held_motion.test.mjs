import {loadSource} from './helpers/source-module.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const {HeldMotion}=await loadSource(new URL('../web/assets/operator/held-motion.js',import.meta.url));
function fixture(send) {
  const jobs=new Map(), calls=[],errors=[];let id=0,now=0;
  const held=new HeldMotion({send:send||(async(i,valid)=>{if(valid())calls.push({...i});}),
    modes:()=>({click_threshold_ms:180,hold_renewal_ms:150}),allowed:()=>true,
    active(){},error:e=>errors.push(e),now:()=>now,
    timer:(fn,ms)=>{jobs.set(++id,{fn,ms});return id;},cancel:i=>jobs.delete(i)});
  return {held,calls,errors,async fire(){const [key,job]=jobs.entries().next().value; jobs.delete(key);now+=job.ms;job.fn();await new Promise(r=>setImmediate(r));}};
}
test('short click emits exactly one pulse, no hold',async()=>{
  const f=fixture();f.held.begin('forward',1);f.held.end(1);await new Promise(r=>setImmediate(r));
  assert.deepEqual(f.calls.map(c=>c.mode),['pulse']);
});
test('hold renews then release keeps only neutral intent',async()=>{
  const f=fixture();f.held.begin('forward',1);await f.fire();await f.fire();
  f.held.end(1);await new Promise(r=>setImmediate(r));
  assert.deepEqual(f.calls.map(c=>c.mode),['hold','hold','release']);
});
test('latest direction wins while transport is busy; old release ignored',async()=>{
  let finish;const calls=[];
  const f=fixture(async(i,valid)=>{calls.push({...i});await new Promise(r=>finish=r);});
  f.held.begin('forward','up');await f.fire();
  f.held.begin('left','left');f.held.begin('backward','down');
  f.held.end('up');assert.equal(f.held.gesture.direction,'backward');
  finish();await new Promise(r=>setImmediate(r));
  assert.deepEqual(calls.map(c=>c.direction),['forward','backward']);
  f.held.stop();finish();
});
test('STOP invalidates a renewal awaiting preparation',async()=>{
  let finish;const calls=[];
  const f=fixture(async(i,valid)=>{await new Promise(r=>finish=r);if(valid())calls.push(i);});
  f.held.begin('forward',1);await f.fire();f.held.stop();finish();
  await new Promise(r=>setImmediate(r));assert.equal(calls.length,0);
});
test('pointer cancellation before hold never emits a pulse',async()=>{
  const f=fixture();f.held.begin('forward',1);f.held.end(1,true);
  await new Promise(r=>setImmediate(r));assert.equal(f.calls.length,0);
});
test('transport failure ends gesture and does not replay movement',async()=>{
  const f=fixture(async()=>{throw new Error('offline');});
  f.held.begin('forward',1);await f.fire();
  assert.equal(f.held.gesture,null);assert.equal(f.errors.length,1);
});
