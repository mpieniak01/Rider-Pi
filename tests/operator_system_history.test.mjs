import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../web/assets/operator/system-history.js',import.meta.url),'utf8');
const {systemHistory,systemEvent}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const row=()=>({hist_ts:[100,101,90,91],hist_mono:[10,11,12,13],hist_generation:[1,1,2,2],hist_seq:[1,2,3,4],hist_cpu:[null,30,40,50],hist_mem:[20,21,22,23],hist_cpu_peak:[null,50,60,70],observation:{monotonic_s:13,age_s:1},sampling:{summary_interval_ms:1000}});
test('wall correction does not reverse monotonic positions; generations split',()=>{
 const h=systemHistory(row(),0,9000);assert.deepEqual(h.points.map(p=>p.age),[4,3,2,1]);
 assert.deepEqual(h.points.map(p=>p.separated),[false,false,true,false]);
 assert.equal(h.points[0].cpu,null);assert.equal(h.points[0].mem,20);
});
test('retained history ages out without replacement measurements',()=>assert.equal(systemHistory(row(),61).count,0));
test('legacy timestamp gaps remain visible',()=>{
 const h=systemHistory({hist_ts:[10,11,20],hist_cpu:[1,2,3],hist_mem:[4,5,6]},0,21);
 assert.deepEqual(h.points.map(p=>p.separated),[false,false,true]);
});
test('missing sequence breaks a curve at normal cadence',()=>{
 const r=row();r.hist_generation=[1,1,1,1];r.hist_seq=[1,2,5,6];
 assert.equal(systemHistory(r).points[2].separated,true);
});

test('restart labels require source identity evidence',()=>{
 const previous={observation:{boot_id:'a',instance_id:'api',generation:1}};
 assert.equal(systemEvent(previous,{observation:{boot_id:'b',instance_id:'new',generation:1}}),'hostRestart');
 assert.equal(systemEvent(previous,{observation:{boot_id:'a',instance_id:'new',generation:1}}),'apiRestart');
 assert.equal(systemEvent(previous,{observation:{boot_id:'a',instance_id:'api',generation:2}}),'samplerResume');
 assert.equal(systemEvent(null,row()),null);
});

test('missing generation cannot prove sampler resumption',()=>{
 assert.equal(systemEvent({observation:{instance_id:'api'}},{observation:{instance_id:'api',generation:1}}),null);
 assert.equal(systemEvent({observation:{instance_id:'api',generation:1}},{observation:{instance_id:'api',generation:Infinity}}),null);
});
