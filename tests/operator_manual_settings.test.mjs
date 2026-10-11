import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const root=new URL('../web/assets/operator/',import.meta.url);
const source=await readFile(new URL('manual-settings-model.js',root),'utf8');
const model=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const values={linear_speed:.2,turn_speed:.35,pulse_duration:.25,speed_limit:.6,linear_rate:3,turn_rate:4};
const limits={linear_speed:1,turn_speed:1,pulse_duration:.25,speed_limit:.6,linear_rate:3,turn_rate:4};
const row=()=>({contract_id:'rider.manual_settings',contract_version:1,revision:0,values:{...values},limits,observed_at:1000,actuation:false});
test('one revision supplies all four signed directions and bounded duration',()=>{
  for(const [direction,vx,yaw] of [['forward',.2,0],['backward',-.2,0],['left',0,-.35],['right',0,.35]]){
    assert.deepEqual(model.settingsPulse(row(),direction),{direction,vx,yaw,duration:.25,settings_revision:0});
  }
  assert.equal(model.settingsValid(row(),1000),true);
  assert.equal(model.settingsValid(row(),1004),false);
  assert.equal(model.settingsValid({...row(),values:{...values,turn_speed:NaN}},1000),false);
});
async function screen(ids, shared){
  const nodes=new Map(ids.map(id=>[id,{id,value:'0',events:{},addEventListener(name,fn){this.events[name]=fn;}}]));
  const raw=(await readFile(new URL('manual-settings.js',root),'utf8')).replace(/^import .*;$/gm,'').replace('export class','class');
  const context=vm.createContext({document:{getElementById:id=>nodes.get(id)||null},window:{addEventListener(){}},
    nowSeconds:()=>1000,settingsValid:model.settingsValid,settingsPulse:model.settingsPulse,
    text(){},tr:(pl,en)=>en,showError(){},clearTimeout(){},setTimeout:()=>1,poll:()=>({stop(){}}),
    request:async(path,options={})=>{
      if(options.method==='POST'){
        assert.equal(options.body.revision,shared.current.revision);
        shared.current={...shared.current,revision:shared.current.revision+1,values:{...shared.current.values,...options.body.values}};
      }
      return {canonical:true,data:structuredClone(shared.current)};
    }});
  const Class=vm.runInContext(raw+';ManualSettings',context);
  const panel=new Class({render(){}});
  await panel.refresh();
  return {panel,nodes};
}
test('calibration writes shared values; control reads identical confirmed values and version',async()=>{
  const shared={current:row()};
  const a=await screen(['calibration-linear-speed','calibration-turn-speed','pulse-duration','motion-linear-rate'],shared);
  const b=await screen(['speed','yaw-speed','duration'],shared);
  a.nodes.get('calibration-turn-speed').value='.5';
  a.nodes.get('calibration-turn-speed').events.input();
  assert.equal(a.panel.ready(),false);
  assert.throws(()=>a.panel.pulse('left'),/unconfirmed/);
  await a.panel.save();
  await b.panel.refresh();
  assert.equal(Number(b.nodes.get('yaw-speed').value),.5);
  assert.equal(a.panel.pulse('left').yaw,b.panel.pulse('left').yaw);
  assert.equal(a.panel.state.revision,b.panel.state.revision);
  assert.equal(b.panel.pulse('right').settings_revision,1);
});
test('invalid or missing remote settings never enable movement',async()=>{
  const shared={current:row()};
  const a=await screen(['speed'],shared);
  shared.current.contract_version=0;
  await assert.rejects(()=>a.panel.refresh(),/unconfirmed/);
  assert.equal(a.panel.ready(),false);
});
