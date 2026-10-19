import {loadSource} from './helpers/source-module.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const root=new URL('../web/assets/operator/',import.meta.url);
const model=await loadSource(new URL('manual-settings-model.js',root));
const values={linear_speed:.2,turn_speed:.35,pulse_duration:.25,speed_limit:.6,linear_rate:3,turn_rate:4,
  linear_deceleration:3,turn_deceleration:4,reversal_pause:0};
const limits={...values,linear_speed:.6,turn_speed:.6,linear_deceleration:100,turn_deceleration:100,reversal_pause:.25};
const descriptions={"parameter_schema": {"version": 1, "direction_fields": {"speed": {"type": "number", "unit": "normalized_command", "display_unit": "%", "display_factor": 100, "minimum": 0, "maximum": 1, "display_precision": 1, "meaning": "command_magnitude_not_physical_speed"}, "minimum": {"type": "number", "unit": "normalized_command", "display_unit": "%", "display_factor": 100, "minimum": 0, "maximum": 1, "display_precision": 1, "meaning": "operator_defined_minimum_nonzero_command"}, "maximum": {"type": "number", "unit": "normalized_command", "display_unit": "%", "display_factor": 100, "minimum": 0, "maximum": 1, "display_precision": 1, "meaning": "profile_command_ceiling"}, "step": {"type": "number", "unit": "normalized_command", "display_unit": "%", "display_factor": 100, "minimum": 0, "maximum": 1, "display_precision": 3, "meaning": "manual_adjustment_step", "exclusive_minimum": true}, "duration": {"type": "number", "unit": "s", "display_unit": "ms", "display_factor": 1000, "minimum": 0.01, "maximum": 1.0, "display_precision": 0, "meaning": "whole_click_pulse"}}, "value_fields": {"linear_rate": {"type": "number", "unit": "normalized_command/s", "display_unit": "%/s", "display_factor": 100, "minimum": 0.001, "maximum": 100.0, "display_precision": 1, "meaning": "linear_rate"}, "turn_rate": {"type": "number", "unit": "normalized_command/s", "display_unit": "%/s", "display_factor": 100, "minimum": 0.001, "maximum": 100.0, "display_precision": 1, "meaning": "turn_rate"}, "linear_deceleration": {"type": "number", "unit": "normalized_command/s", "display_unit": "%/s", "display_factor": 100, "minimum": 0.001, "maximum": 100.0, "display_precision": 1, "meaning": "linear_deceleration"}, "turn_deceleration": {"type": "number", "unit": "normalized_command/s", "display_unit": "%/s", "display_factor": 100, "minimum": 0.001, "maximum": 100.0, "display_precision": 1, "meaning": "turn_deceleration"}, "reversal_pause": {"type": "number", "unit": "s", "display_unit": "ms", "display_factor": 1000, "minimum": 0, "maximum": 0.25, "display_precision": 0, "meaning": "pause_before_reversal"}}, "constraints": [{"id": "direction_range", "rule": "minimum <= maximum"}, {"id": "direction_speed", "rule": "speed == 0 or minimum <= speed <= maximum"}, {"id": "direction_step", "rule": "step > 0; zero-width range permits a disabled slider"}, {"id": "pulse_minimum", "rule": "minimum <= duration / (1/acceleration + 1/deceleration)"}]}, "control_modes": {"version": 1, "supported": ["pulse", "hold", "release"], "default": "pulse", "directions": ["forward", "backward", "left", "right"], "hold_renewal_ms": 150, "hold_timeout_ms": 500, "click_threshold_ms": 180, "request_ttl_ms": 500, "replacement": "latest_valid_sequence_wins", "release": "decelerate_keep_armed", "release_timeout_ms": 500, "stop": "immediate_disarm", "hold_permission": "operator_manual_panel", "settings_change": "idle_only", "command": {"endpoint": "/api/control", "action": "move", "fields": ["direction", "mode", "device_settings", "settings_revision"]}}};
const row=()=>({contract_id:'rider.manual_settings',contract_version:2,schema_version:2,authority:'device',revision:0,
  ...structuredClone(descriptions),values:{...values},limits,directions:Object.fromEntries(model.directions.map(name=>[name,
    {minimum:0,maximum:.6,step:.01,speed:['forward','backward'].includes(name)?.2:.35,duration:.25}])),
  observed_at:1000,actuation:false});
test('panel sends direction and revision only; Pi maps commands',()=>{
  for(const direction of model.directions)
    assert.deepEqual(model.settingsPulse(row(),direction),{direction,device_settings:true,settings_revision:0});
  assert.equal(model.settingsValid(row(),1000),true);
  assert.equal(model.settingsValid(row(),1004),false);
  assert.equal(model.settingsValid({...row(),directions:{}},1000),false);
  assert.equal(model.settingsValid({...row(),contract_version:1},1000),false);
});
async function screen(shared,{postError=null,nodes={},elFactory=()=>({})}={}){
  const raw=(await readFile(new URL('manual-settings.js',root),'utf8')).replace(/^import .*;$/gm, line => line.replace(/[^\n]/g, ' ')).replace('export class','       class');
  let posts=0;
  const context=vm.createContext({document:{getElementById:id=>nodes[id]||null},window:{addEventListener(){}},
    nowSeconds:()=>1000,settingsValid:model.settingsValid,settingsPulse:model.settingsPulse,
    fields:model.fields,directions:model.directions,parameter:model.parameter,displayFactor:model.displayFactor,descriptionsValid:model.descriptionsValid,displayValue:model.displayValue,formatParameter:model.formatParameter,parameterRange:model.parameterRange,el:elFactory,text(){},tr:(pl,en)=>en,showError(){},
    poll:()=>({stop(){}}),request:async(path,options={})=>{
      if(options.method==='POST'){
        posts++;
        if(postError)throw postError;
        assert.equal(options.body.revision,shared.current.revision);
        shared.current={...shared.current,revision:shared.current.revision+1,
          values:{...shared.current.values,...options.body.values},
          directions:{...shared.current.directions,...Object.fromEntries(Object.entries(options.body.directions||{})
            .map(([key,value])=>[key,{...shared.current.directions[key],...value}]))}};
        shared.current.values.speed_limit=Math.max(...Object.values(shared.current.directions).map(row=>row.maximum));
      }
      return {canonical:true,data:structuredClone(shared.current)};
    }});
  const Class=vm.runInContext(raw+';ManualSettings',context,{filename:new URL('manual-settings.js',root).href});
  const panel=new Class({state:{state:'ARMED'},clockFresh:()=>true,render(){}});
  await panel.refresh();
  return {panel,posts:()=>posts};
}
test('armed calibration saves settings and control reads identical revision',async()=>{
  const shared={current:row()}, a=await screen(shared), b=await screen(shared);
  assert.equal(a.panel.editable(),true);
  a.panel.edit(()=>{a.panel.directionEdits.left={speed:.5};});
  assert.equal(a.panel.ready(),false);
  assert.throws(()=>a.panel.pulse('left'),/unconfirmed/);
  await a.panel.save();await b.panel.refresh();
  assert.equal(a.panel.state.directions.left.speed,.5);
  assert.equal(b.panel.state.directions.left.speed,.5);
  assert.equal(a.panel.state.revision,b.panel.state.revision);
  assert.equal(b.panel.pulse('right').settings_revision,1);
});
test('conflict is displayed and never automatically retried',async()=>{
  const shared={current:row()};
  const a=await screen(shared,{postError:Object.assign(new Error('conflict'),{status:409})});
  a.panel.edit(()=>{a.panel.directionEdits.forward={speed:.3};});
  shared.current.revision++;
  await assert.rejects(()=>a.panel.save(),/Write rejected/);
  assert.equal(a.posts(),1);
  assert.equal(a.panel.state.revision,1);
  assert.equal(a.panel.dirty(),false);
});
test('unconfirmed remote values block movement',async()=>{
  const shared={current:row()}, a=await screen(shared);
  shared.current.contract_version=0;
  await assert.rejects(()=>a.panel.refresh(),/unconfirmed/);
});


test('slider expands bounds before receiving a larger authoritative value',async()=>{
  let magnitude=.2;
  const slider={max:.2,min:0,step:.01,get value(){return magnitude;},set value(x){magnitude=Math.min(Number(x),Number(this.max));}};
  const shared={current:row()};
  shared.current.directions.forward={...shared.current.directions.forward,maximum:.2,speed:.2};
  const a=await screen(shared,{nodes:{'setting-forward-speed':slider}});
  shared.current.revision++;
  shared.current.directions.forward={...shared.current.directions.forward,maximum:.6,speed:.4};
  await a.panel.refresh();
  assert.equal(slider.value,40);
  assert.equal(a.panel.state.directions.forward.speed,.4);
});


test('active profile is selected after the first confirmed read',async()=>{
  const shared={current:{...row(),active_profile:'preset',profiles:{preset:{name:'Desk'}}}};
  const select={dataset:{},replaceChildren(){},addEventListener(){}};
  const a=await screen(shared,{nodes:{'motion-profile-select':select}});
  assert.equal(a.panel.selectedProfile,'preset');
  assert.equal(select.value,'preset');
});

test('invalid stored step never rounds the displayed slider down to zero',async()=>{
  let magnitude=0;
  const slider={max:60,min:0,step:1,get value(){return magnitude;},set value(x){
    magnitude=this.step==='any'?Number(x):Math.round(Number(x)/Number(this.step))*Number(this.step);
  }};
  const shared={current:row()};
  shared.current.directions.backward={...shared.current.directions.backward,step:1,speed:.6};
  const a=await screen(shared,{nodes:{'setting-backward-speed':slider}});
  assert.equal(slider.value,60);
  assert.equal(slider.step,'any');
  assert.equal(a.panel.ready(),false);
  assert.ok(a.panel.validation().some(e=>e.id==='setting-backward-step'));
  a.panel.edit(()=>{a.panel.directionEdits.backward={step:.01};});
  await a.panel.save();
  assert.equal(shared.current.directions.backward.step,.01);
  assert.equal(shared.current.directions.backward.speed,.6);
});

test('invalid duration is caught before POST and draft is retained',async()=>{
  const a=await screen({current:row()});
  a.panel.edit(()=>{a.panel.directionEdits.backward={duration:1.001};});
  await assert.rejects(()=>a.panel.save(),/10–1000 ms/);
  assert.equal(a.posts(),0);
  assert.equal(a.panel.directionEdits.backward.duration,1.001);
  assert.equal(a.panel.dirty(),true);
});

test('server validation error retains editable draft and never retries',async()=>{
  const a=await screen({current:row()},{postError:Object.assign(new Error('validation'),{status:400})});
  a.panel.edit(()=>{a.panel.directionEdits.forward={speed:.3};});
  await assert.rejects(()=>a.panel.save(),/validation/);
  assert.equal(a.posts(),1);
  assert.equal(a.panel.directionEdits.forward.speed,.3);
  assert.equal(a.panel.dirty(),true);
  assert.equal(a.panel.ready(),false);
});

test('milliseconds and percent display preserve canonical units',async()=>{
  const duration={},rate={},speed={};
  const a=await screen({current:row()},{nodes:{
    'setting-forward-duration':duration,'setting-linear_rate':rate,'setting-forward-speed':speed}});
  assert.equal(duration.value,250);
  assert.equal(rate.value,300);
  assert.equal(speed.value,20);
  assert.equal(a.panel.state.directions.forward.duration,.25);
  assert.equal(a.panel.state.directions.forward.speed,.2);
});

test('typing percent and milliseconds converts once before persistence',async()=>{
  const factory=()=>({dataset:{},children:[],value:'',append(...nodes){this.children.push(...nodes);},
    addEventListener(event,fn){this[event]=fn;}});
  const shared={current:row()},a=await screen(shared,{elFactory:factory});
  for(const [key,display,canonical] of [['step','1',.01],['duration','200',.2],['speed','35',.35]]){
    const label=a.panel.input('setting-backward-'+key,key,value=>{
      a.panel.directionEdits.backward={...a.panel.directionEdits.backward,[key]:value};
    });
    const node=label.children[1];node.value=display;node.input();
    assert.equal(a.panel.directionEdits.backward[key],canonical);
  }
  await a.panel.save();
  assert.equal(shared.current.directions.backward.speed,.35);
  assert.equal(shared.current.directions.backward.step,.01);
  assert.equal(shared.current.directions.backward.duration,.2);
});

test('one second duration and full calibrated maximum pass UI validation',async()=>{
  const shared={current:row()};
  shared.current.limits={...limits,speed_limit:1,linear_speed:1,turn_speed:1,pulse_duration:1,linear_rate:100,turn_rate:100};
  const a=await screen(shared);
  a.panel.edit(()=>{a.panel.directionEdits.backward={maximum:1,speed:1,duration:1};});
  assert.equal(a.panel.validation().length,0);
  await a.panel.save();
  assert.equal(shared.current.directions.backward.speed,1);
  assert.equal(shared.current.directions.backward.duration,1);
});

test('calibration readback updates control bounds, duration and slider in percent',async()=>{
  const shared={current:row()},slider={},duration={};
  const control=await screen(shared,{nodes:{'setting-backward-speed':slider,'setting-backward-duration':duration}});
  shared.current.limits={...limits,speed_limit:1,linear_speed:1,turn_speed:1,pulse_duration:1};
  shared.current.values.speed_limit=1;
  shared.current.revision++;
  shared.current.directions.backward={...shared.current.directions.backward,maximum:1,step:.02,speed:.42,duration:.8};
  await control.panel.refresh();
  assert.equal(slider.value,42);
  assert.equal(slider.max,100);
  assert.equal(duration.value,800);
  assert.equal(control.panel.state.directions.backward.step,.02);
});

test('remote active profile changes are reflected unless operator is choosing another',async()=>{
  const shared={current:{...row(),profiles:{a:{name:'Desk'},b:{name:'Floor'}},active_profile:'a'}};
  const select={dataset:{},replaceChildren(){},addEventListener(){}};
  const a=await screen(shared,{nodes:{'motion-profile-select':select}});
  shared.current={...shared.current,revision:1,active_profile:'b'};
  await a.panel.refresh();
  assert.equal(select.value,'b');
  a.panel.profileSelectionDirty=true;a.panel.selectedProfile='a';
  shared.current.revision++;
  await a.panel.refresh();
  assert.equal(select.value,'a');
});

test('parameter descriptions drive time bounds instead of client constants',async()=>{
  const current=row();current.parameter_schema.direction_fields.duration.maximum=2;
  current.limits.pulse_duration=2;current.directions.forward.duration=1.5;
  const a=await screen({current});
  assert.equal(a.panel.validation().length,0);
  assert.equal(a.panel.factor('duration'),1000);
});
test('unknown descriptor version blocks mutation',async()=>{
  const current=row();current.parameter_schema.version=99;
  await assert.rejects(()=>screen({current}),/unconfirmed/);
});

test('slider step starts at calibrated minimum and preserves zero',async()=>{
  const factory=()=>({dataset:{},children:[],value:'',append(...nodes){this.children.push(...nodes);},
    addEventListener(event,fn){this[event]=fn;}});
  const current=row();current.directions.forward={...current.directions.forward,minimum:.15,step:.1};
  const a=await screen({current},{elFactory:factory});
  const label=a.panel.input('setting-forward-speed','speed',value=>{a.panel.directionEdits.forward={speed:value};});
  const node=label.children[1];node.value='26';node.input();
  assert.equal(a.panel.directionEdits.forward.speed,.25);
  node.value='0';node.input();
  assert.equal(a.panel.directionEdits.forward.speed,0);
});

test('all panel presentations follow device units, including feedback and captions',async()=>{
  const current=row();
  current.parameter_schema.direction_fields.duration.display_unit='s';
  current.parameter_schema.direction_fields.duration.display_factor=1;
  current.parameter_schema.value_fields.reversal_pause.display_unit='s';
  current.parameter_schema.value_fields.reversal_pause.display_factor=1;
  current.parameter_schema.value_fields.linear_rate.display_unit='level/s';
  current.parameter_schema.value_fields.linear_rate.display_factor=1;
  const title={},duration={parentElement:{querySelector:()=>title,append(){}},setAttribute(){}},feedback={};
  const a=await screen({current},{nodes:{'setting-forward-duration':duration,'manual-settings-feedback':feedback}});
  assert.equal(duration.value,.25);assert.equal(duration.max,1);
  assert.equal(title.textContent,'Pulse (s)');
  assert.match(feedback.textContent,/3 level\/s/);
  assert.match(feedback.textContent,/Reversal: 0 s/);
  assert.equal(a.panel.range('duration'),'0,01–1 s');
});
test('formatter rounds labels to descriptor precision while inputs retain exact values',()=>{
  const current=row();
  assert.equal(model.formatParameter(current,'speed',.0055,'en'),'0.6%');
  assert.equal(model.formatParameter(current,'duration',.2505,'en'),'251 ms');
  assert.equal(model.formatParameter(null,'duration',.25),'—');
});

test('computed repeating fractions use device precision without changing editable values',()=>{
  const current=row();
  assert.equal(model.formatParameter(current,'speed',.25/(1/.5+1/1),'pl'),'8,3%');
  assert.equal(model.formatParameter(current,'speed',.25/(1/.5+1/1),'en'),'8.3%');
  assert.equal(model.formatParameter(current,'speed',.6,'pl'),'60%');
  assert.equal(model.formatParameter(current,'speed',NaN,'pl'),'—');
  assert.equal(model.displayValue(current,'speed',.0055),.55);
  assert.equal(model.displayValue(current,'duration',.2505),250.5);
  assert.equal(current.values.linear_rate,3);
});

test('curve selection is validated and saved in the common robot settings',async()=>{
  const current=row();
  current.values.ramp_mode=0;current.limits.ramp_mode=2;
  current.parameter_schema.ramp_modes=[{value:0},{value:1},{value:2}];
  const shared={current}, a=await screen(shared), b=await screen(shared);
  a.panel.edit(()=>{a.panel.pending.ramp_mode=1;});
  await a.panel.save();await b.panel.refresh();
  assert.equal(b.panel.state.values.ramp_mode,1);
  const bad=structuredClone(shared.current);bad.values.ramp_mode=3;
  assert.equal(model.settingsValid(bad,100),false);
});
