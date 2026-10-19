import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const raw=(await readFile(new URL('../web/assets/operator/remote-navigation.js',import.meta.url),'utf8'))
  .replace(/^import .*;$/gm, line => line.replace(/[^\n]/g, ' ')).replace('export class','       class');
function fixture({mode='observe',fail=false}={}) {
 const calls=[],nodes={}, policy={revision:4,mode,speed:.1,decision_budget_ms:300,max_motion_ms:150,
  calibration_id:'trial',model_sha256:'a'.repeat(64),corridor:[.35,.65,.65,.95],verified:true};
 const node=id=>nodes[id]??=( {value:'',checked:false,addEventListener(){}} );
 const context=vm.createContext({document:{getElementById:node},tr:(_pl,en)=>en,text(){},showError(){},
 request:async(path,options={})=>{
  calls.push({path,...options});
  if(fail&&options.method==='POST')throw new Error('conflict');
  return {data:path.endsWith('status')?{stale:true}:structuredClone(policy)};
 }});
 const Class=vm.runInContext(raw+';RemoteNavigation',context,{filename:new URL('../web/assets/operator/remote-navigation.js',import.meta.url).href});
 const safety={state:{manual_settings:{revision:8}},prepare:async()=>calls.push({prepare:true}),
  envelope:()=>({generation:'g',seq:3,source:'navigation',ts:100,ttl_ms:500,request_id:'fresh'}),
  send:async(...args)=>calls.push({send:args}),stop:async()=>calls.push({stop:true})};
 return {panel:new Class(safety),calls,nodes,node};
}
test('opening panel has no network or hardware effects',()=>{
 assert.deepEqual(fixture().calls,[]);
});
test('configuration is saved through device revision API only',async()=>{
 const f=fixture();await f.panel.load();
 f.node('remote-speed').value='.12';await f.panel.save();
 const posts=f.calls.filter(c=>c.method==='POST');
 assert.equal(posts.length,1);assert.equal(posts[0].path,'/api/navigation/config');
 assert.equal(posts[0].body.revision,4);assert.equal(posts[0].body.values.speed,.12);
 assert.equal(f.calls.some(c=>c.send||c.stop),false);
});
test('observation starts without arming or motion envelope',async()=>{
 const f=fixture();await f.panel.run(false);
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].path,'/api/logic/feature/s15_venom_perception');
 assert.equal(f.calls[0].body.generation,undefined);
});
test('drive requires policy and uses fresh settings authority',async()=>{
 const f=fixture({mode:'drive'});
 await assert.rejects(()=>f.panel.run(true),/Save drive/);
 await f.panel.load();await f.panel.run(true);
 const command=f.calls.at(-1);
 assert.equal(command.path,'/api/logic/feature/s14_venom_navigation');
 assert.equal(command.body.settings_revision,8);assert.equal(command.body.generation,'g');
 assert.equal(command.body.source,'navigation');assert.equal(command.body.request_id,'fresh');
 assert.equal(f.calls.some(c=>c.send),false);
});
test('STOP precedes service removal; failed write is not retried',async()=>{
 const f=fixture();await f.panel.stop();
 assert.equal(f.calls[0].stop,true);
 assert.deepEqual(f.calls.slice(1).map(c=>[c.path,c.body.enabled]),[
 ['/api/logic/feature/s14_venom_navigation',false],['/api/logic/feature/s15_venom_perception',false]]);
 const bad=fixture({fail:true});await bad.panel.load();
 await assert.rejects(()=>bad.panel.save(),/conflict/);
 assert.equal(bad.calls.filter(c=>c.method==='POST').length,1);
});
