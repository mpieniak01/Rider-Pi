// Exercise the real page entrypoint with inert UI components, never a robot transport.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const file=new URL('../web/assets/operator/app.js',import.meta.url);
const source=await readFile(file,'utf8');
async function mount(page){
 const instances=[],listeners=new Map();let receive;
 const button=()=>({setAttribute(){},append(){},disabled:true});
 const context=vm.createContext({console,localStorage:{getItem:()=> 'en'},setInterval:()=>1,
  document:{body:{dataset:{page}},querySelector:()=>({append(){}}),getElementById:()=>null,querySelectorAll:()=>[]},
  window:{addEventListener:(event,fn)=>listeners.set(event,[...(listeners.get(event)||[]),fn])}});
 const exports=new Map();
 for(const match of source.matchAll(/import \{([^}]+)\} from ['"]([^'"]+)['"]/g)){
  const names=match[1].split(',').map(name=>name.trim());
  exports.set(match[2],new vm.SyntheticModule(names,function(){
   for(const name of names){
    let value=()=>{};
    if(/^[A-Z]/.test(name)) value=class{
     constructor(...args){this.kind=name;this.args=args;this.state={state:'DISARMED'};this.revokedGenerations=new Set();this.poller={stop:()=>{this.stopped=true;}};instances.push(this);}
     can(){return false;}clockFresh(){return false;}render(){}event(){}renderTelemetry(){}
     update(state){this.state=state;}ack(data){this.lastAck=data;}
    };
    else if(name==='el')value=button;
    else if(name==='events')value=callback=>{receive=callback;};
    else if(name==='fresh'||name==='catalogKnown'||name==='safetyKnown')value=()=>false;
    else if(name==='tr')value=(pl,en)=>en;
    this.setExport(name,value);
   }
  },{context}));
 }
 const module=new vm.SourceTextModule(source,{context,identifier:file.href});
 await module.link(name=>exports.get(name));await module.evaluate();
 return {instances,hide:(persisted=false)=>listeners.get('pagehide').forEach(fn=>fn({persisted})),receive};
}
for(const [page,component] of [['control','ControlCamera'],['devices','Devices'],['navigation','RemoteNavigation']]){
 test(page+' retains the mounted controller and closes its poller on pagehide',async()=>{
  const f=await mount(page);const panel=f.instances.find(row=>row.kind===component);
  assert.ok(panel);assert.equal(panel.stopped,undefined);
  f.hide(true);assert.equal(panel.stopped,undefined,'browser cache restoration must retain live poller');
  f.hide();assert.equal(panel.stopped,true);
  const safety=f.instances.find(row=>row.kind==='SafetyPanel');assert.equal(safety.args[1].interactive,page==='control');
 });
}
test('entrypoint routes safety observations and acknowledgements without issuing control',async()=>{
 const f=await mount('system');const safety=f.instances.find(row=>row.kind==='SafetyPanel');
 f.receive({topic:'motion.state',data:JSON.stringify({contract_version:1,state:'DISARMED'}),ts:1});
 assert.equal(safety.state.state,'DISARMED');
 f.receive({topic:'motion.ack',data:{status:'rejected'},ts:2});assert.equal(safety.lastAck.status,'rejected');
});
