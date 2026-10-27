import assert from 'node:assert/strict';
import test from 'node:test';
import {fixture,disarmed,capability} from './helpers/operator-fixture.mjs';
function ready(){
 return {...disarmed(),ready:true,stale:false,panel_control:{version:1,holder:null},
 operator_intervention_version:1,operator_height_intervention_version:1,operator_posture_intervention_version:1,
 capabilities:{move:capability,turn:capability,height:capability,balance:capability}};
}
function controls(f){f.panel.controls={state:{revision:45},commandReady:()=>true};}
for(const [action,params] of [['height',{height:95}],['balance',{enabled:false}]]){
 test(action+' is one explicit gesture while disarmed with its own panel identity',async()=>{
  const f=await fixture(ready());controls(f);
  assert.equal(f.panel.can('manual',action),true);
  await f.panel.send(action,params);
  const posts=f.calls.filter(row=>row.method==='POST');
  assert.equal(posts.length,1);const body=posts[0].body;
  assert.equal(body.action,action);assert.equal(body.operator_intervention_version,1);
  assert.equal(body.panel_id,f.panel.panelId);assert.equal(body.operator_consent,true);
  assert.equal(body.settings_revision,45);assert.equal(body.device_settings,true);
  assert.equal(body.owner,'manual');assert.equal(body.arming_mode,'operator');
 });
}
test('new panel must not borrow another panel permission for posture',async()=>{
 const f=await fixture({...ready(),state:'ARMED',owner:'manual',arming_mode:'operator',execution_context:'panel',panel_control:{version:1,holder:'venom-panel'}});controls(f);
 await f.panel.send('height',{height:95});
 const body=f.calls.find(row=>row.method==='POST').body;
 assert.notEqual(body.panel_id,'venom-panel');assert.equal(body.intervene,true);
});
test('ESTOP and stale observations never authorize native gestures',async()=>{
 for(const patch of [{state:'ESTOP'},{stale:true},{ready:false}]){
  const f=await fixture({...ready(),...patch});controls(f);
  assert.equal(f.panel.can('manual','height'),false);
  await assert.rejects(f.panel.send('height',{height:95}));
  assert.equal(f.calls.filter(row=>row.method==='POST').length,0);
 }
});

test('an unsaved drive draft does not block an independent height target',async()=>{
 const f=await fixture(ready());controls(f);f.panel.controls.commandReady=()=>false;
 assert.equal(f.panel.can('manual','height'),true);
 assert.equal(f.panel.can('manual','move'),false);
 await f.panel.send('height',{height:95});
 assert.equal(f.calls.filter(row=>row.method==='POST').length,1);
});
test('a stale armed operator state does not authorize a new explicit gesture',async()=>{
 const f=await fixture({...ready(),state:'ARMED',owner:'manual',arming_mode:'operator',execution_context:'panel',stale:true});controls(f);
 assert.equal(f.panel.can('manual','height'),false);
});
