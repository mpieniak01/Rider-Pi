import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {loadSource} from './helpers/source-module.mjs';
import {domNode} from './helpers/sonar307-dom.mjs';

const assets=new URL('../web/assets/operator/',import.meta.url);
const model=await loadSource(new URL('model.js',assets));
const observation=await loadSource(new URL('observations.js',assets));
const held={HeldMotion:class{}};
const element=()=>({dataset:{},children:[],value:'',classList:{add(){},remove(){},toggle(){}},
  append(...items){this.children.push(...items);},appendChild(item){this.children.push(item);},
  replaceChildren(...items){this.children=items;},addEventListener(){},querySelectorAll:()=>[],
  setAttribute(){},querySelector:()=>null});
async function fixture(file,{globals={},replacements={}}={}) {
  const requests=[],nodes=new Map(),timers=new Map();
  const node=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const context=vm.createContext({AbortController,Headers,URL,URLSearchParams,Date,
    sessionStorage:{getItem:()=>null,setItem(){}},
    document:{hidden:false,getElementById:node,querySelectorAll:()=>[],body:{dataset:{page:'control'}},
      documentElement:{lang:'en'},addEventListener(){},removeEventListener(){}},
    window:{addEventListener(){}},setInterval:()=>1,clearInterval(){},
    setTimeout:fn=>{const key=Symbol();timers.set(key,fn);return key;},clearTimeout:key=>timers.delete(key),
    ...globals});
  const modules={
    'model.js':model,'held-motion.js':held,
    'request-id.js':{requestId:()=> 'fixture-id'},
    'transport.js':{request:async(path,options={})=>{requests.push({path,...options});return {status:202,data:{pending:true,providers:[]}};},
      poll:()=>({refresh(){},stop(){}}),prepareMutation:async()=>{}},
    'ui.js':{text(){},tr:(_pl,en)=>en,statusLabel:String,showError:error=>{throw error;},el:element,
      pill:element,freshPill:element,button:element,kv:element,ageLabel:()=>'',ageStamp:element,rawDetails:element},
    ...replacements,
  };
  const cache=new Map();
  async function load(url) {
    url=new URL(url);url.search='';
    if(!cache.has(url.href))cache.set(url.href,(async()=>{
      const replacement=modules[url.pathname.split('/').at(-1)];
      if(replacement)return new vm.SyntheticModule(Object.keys(replacement),function(){
        for(const [key,value] of Object.entries(replacement))this.setExport(key,value);
      },{context,identifier:url.href});
      return new vm.SourceTextModule(await readFile(url,'utf8'),{context,identifier:url.href});
    })());
    return cache.get(url.href);
  }
  const loaded=await load(new URL(file,assets));
  await loaded.link((specifier,parent)=>load(new URL(specifier,parent.identifier)));
  await loaded.evaluate();
  return {namespace:loaded.namespace,requests,node,nodes,timers,context};
}
function safetyOf(f) {
  const panel=Object.create(f.namespace.SafetyPanel.prototype);
  Object.assign(panel,{mutating:false,controlsActive:()=>true,render(){},renderHistory(){},poller:{refresh(){}},
    history:[],pending:new Map(),held:{stop(){}},toggleEpoch:0,revoke(){},commandTime:()=>1000});
  return panel;
}

test('invalid safety parameters fail before negotiation, envelope creation or transport',async()=>{
  const f=await fixture('safety.js'),panel=safetyOf(f);
  panel.prepare=async()=>assert.fail('No negotiation for invalid parameters');
  for(const [action,params] of [
    ['arm',{lease_s:31}],['move',{vx:1,yaw:0,duration:.251}],
    ['height',{height:74}],['action',{action_id:0}],
  ])await assert.rejects(panel.send(action,params));
  assert.equal(f.requests.length,0);assert.equal(panel.pending.size,0);assert.equal(panel.mutating,false);
});

test('exempt STOP remains available during mutation without permission preparation',async()=>{
  const f=await fixture('safety.js'),panel=safetyOf(f),events=[];
  Object.assign(panel,{mutating:true,controlsActive:()=>false,held:{stop:()=>events.push('held-stop')},
    revoke:()=>events.push('revoke'),prepare:async()=>assert.fail('STOP must not prepare'),
    envelope:()=>assert.fail('STOP must not require a motion envelope')});
  const result=await panel.send('stop');
  assert.equal(result.pending,true);
  assert.deepEqual(events,['held-stop','revoke']);
  assert.equal(f.requests.length,1);
  assert.equal(f.requests[0].path,'/api/control');
  assert.equal(f.requests[0].body.action,'stop');
  assert.equal(f.requests[0].body.generation,undefined);
  assert.equal(panel.history[0].status,'pending');
});

test('failed preparation clears the pending lock and creates no command',async()=>{
  const f=await fixture('safety.js'),panel=safetyOf(f);
  panel.prepare=async()=>{throw new Error('stale fixture');};
  panel.envelope=()=>assert.fail('No envelope after failed preparation');
  await assert.rejects(panel.send('height',{height:90}),/stale fixture/);
  assert.equal(panel.mutating,false);assert.equal(panel.pending.size,0);assert.equal(f.requests.length,0);
});

test('settings revision changed during refresh requires a new operator click',async()=>{
  const f=await fixture('safety.js'),panel=safetyOf(f);
  panel.state={arming_mode:'lease'};
  panel.controls={state:{revision:1},pulse:direction=>({direction,device_settings:true,settings_revision:1}),
    async refresh(){this.state.revision=2;}};
  panel.prepare=async()=>{};
  panel.envelope=()=>assert.fail('Changed settings must not create an envelope');
  await assert.rejects(panel.send('move',{direction:'forward'}),/Settings changed/);
  assert.equal(panel.mutating,false);assert.equal(f.requests.length,0);
});

test('chat constructor is synchronous and provider reads begin only when mounted explicitly',async()=>{
  const f=await fixture('chat.js');
  const chat=new f.namespace.Chat({});
  assert.equal(f.requests.length,0);
  await chat.loadProviders();
  assert.deepEqual(f.requests.map(row=>row.path),['/api/voice/providers']);
  assert.equal(f.requests[0].method,undefined);
});

test('transport beforeSend failure cancels the timer without calling fetch',async()=>{
  let fetched=0;
  const f=await fixture('transport.js',{globals:{fetch:async()=>{fetched++;throw new Error('Unexpected fetch');}},
    replacements:{'transport.js':null}});
  await assert.rejects(f.namespace.request('/api/control/state',{beforeSend(){throw new Error('cancel fixture');}}),/cancel fixture/);
  assert.equal(fetched,0);assert.equal(f.timers.size,0);
});

test('canonical body with unnegotiated MIME remains read only and clears its timer',async()=>{
  let fetched=0;
  const meta={envelope_version:1,contract_id:'rider.safety',contract_version:1,server_time:1000};
  const f=await fixture('transport.js',{globals:{fetch:async()=>{fetched++;return {
    ok:true,status:200,headers:new Headers({'Content-Type':'application/json'}),
    json:async()=>({ok:true,data:{server_time:1000},meta,error:null}),
  };}},replacements:{'transport.js':null}});
  await assert.rejects(f.namespace.request('/api/control/state'),/Content-Type/);
  assert.equal(fetched,1);assert.equal(f.timers.size,0);
});

const motionSample=()=>({
  contract_id:'rider.telemetry',contract_version:1,source:'motion',observed_at:1000,
  uart_owner:'motion-executor',instance_id:'i',generation:'g',hardware_ready:true,
  sensor_quality:{sensors:{battery:{value:.5,unit:'ratio',observed_at:999.8,assessed_at:1000,
    age_s:.2,max_age_s:100,ready:true,instance_id:'i',generation:'g'}}},
});
test('measurement freshness uses capture assessment and clamps source maximum age',()=>{
  const input=motionSample();
  assert.equal(observation.observationChannel(input,'battery',{now:1000,requireMotion:true}).value,50);
  const late=observation.observationChannel(input,'battery',{now:1002.6,requireMotion:true});
  assert.equal(late.ready,false);assert.equal(late.status,'stale');assert.equal(late.raw_value,.5);
  assert.equal(late.value,null);
});

test('motion measurements require exact current parent identity and never inherit future source time',()=>{
  for(const patch of [{instance_id:'different'},{generation:'different'},{observed_at:1000.05},{age_s:-1}]){
    const sample=motionSample();Object.assign(sample.sensor_quality.sensors.battery,patch);
    const value=observation.observationChannel(sample,'battery',{now:1000,requireMotion:true});
    assert.equal(value.ready,false,JSON.stringify(patch));
    assert.equal(value.value,null);
  }
  const sample=motionSample();sample.hardware_ready=false;
  assert.equal(observation.observationChannel(sample,'battery',{now:1000,requireMotion:true}).error,'motion_parent_unconfirmed');
});

test('legacy percent and ratio adapters do not infer units from numeric value',()=>{
  const options={now:1000};
  assert.equal(observation.observationChannel({battery_pct:1,observed_at:1000},'battery',options).value,1);
  const legacy={observed_at:1000,sensor_quality:{battery:{value:1,observed_at:1000,ready:true}}};
  assert.equal(observation.observationChannel(legacy,'battery',options).value,100);
  const canonical={...legacy,contract_id:'rider.telemetry',contract_version:1};
  assert.equal(observation.observationChannel(canonical,'battery',options).ready,false);
});

test('parent partial-sensor error preserves an independent healthy channel but transport flags block it',()=>{
  const sample=motionSample();sample.error='sensor_quality:partial';
  assert.equal(observation.observationChannel(sample,'battery',{now:1000}).ready,true);
  for(const patch of [{meta:{offline:true}},{meta:{stale:true}},{simulated:true},{battery_ok:false}]){
    const row=observation.observationChannel({...sample,...patch},'battery',{now:1000});
    assert.equal(row.ready,false);assert.equal(row.raw_value,.5);
  }
});

test('Google Home module resolves from either page URL and startup reads never send commands',async()=>{
  const calls=[],nodes=new Map(),cards=[];
  function node(selector){
    if(!nodes.has(selector))nodes.set(selector,domNode());
    return nodes.get(selector);
  }
  node('#devicesList').appendChild=card=>cards.push(card);
  const device={name:'devices/<fixture>',type:'light',traits:{
    'sdm.devices.traits.OnOff':{on:true},'sdm.devices.traits.Brightness':{brightness:0},
    'sdm.devices.traits.ColorSetting':{temperatureK:3000,spectrumRgb:1},
    'sdm.devices.traits.TemperatureSetting':{thermostatTemperatureSetpoint:20,thermostatTemperatureAmbient:19,availableThermostatModes:['off']},
    'sdm.devices.traits.StartStop':{isRunning:true,isPaused:true},
  }};
  await fixture('../google-home.js',{globals:{
    document:{documentElement:{setAttribute(){}},querySelector:node,querySelectorAll:()=>[],createElement:domNode},
    localStorage:{getItem:()=>null,setItem(){}},navigator:{language:'en'},location:{search:'',pathname:'/google_home'},
    window:{addEventListener(){},history:{replaceState(){}}},
    fetch:async(path,options={})=>{calls.push({path,...options});return {ok:true,status:200,json:async()=>path.endsWith('/status')?{authenticated:true}:{ok:true,devices:[device]}};},
  },replacements:{'i18n.js':{initI18n:async()=>{},applyDom(){},t:key=>key}}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(cards.length,1);
  assert.match(cards[0].innerHTML,/&lt;fixture&gt;/);
  assert.match(cards[0].innerHTML,/PAUSED/);
  assert.match(cards[0].innerHTML,/data-action="thermostat-mode"/);
  assert.ok(calls.every(row=>!row.method||row.method==='GET'));
  const html=await readFile(new URL('../web/google_home.html',import.meta.url),'utf8');
  const src=html.match(/<script type="module" src="([^"]*google-home.js)"/)[1];
  for(const page of ['/google_home','/web/google_home.html']){
    assert.equal(new URL(src,'http://fixture'+page).pathname,'/web/assets/google-home.js');
  }
});


test('task envelope and dispatch stay in one continuation before queued epoch invalidation',async()=>{
  const events=[];
  const transport={request:async()=>{events.push('dispatch');return {status:202,data:{pending:true}};},
    poll:()=>({refresh(){}}),prepareMutation:async()=>{}};
  const f=await fixture('tasks.js',{replacements:{
    'transport.js':transport,
    'model.js':{...model,catalogKnown:()=>true,taskCanStart:()=>true,nowSeconds:()=>1000},
  }});
  const tasks=Object.create(f.namespace.Tasks.prototype);
  Object.assign(tasks,{catalog:{},busy:new Set(),options:new Map(),results:new Map(),render(){},poller:{refresh(){}},
    safety:{state:{},poller:{refresh(){}},prepare:async()=>{},
      envelope(){events.push('envelope');Promise.resolve().then(()=>events.push('queued-epoch-change'));
        return {generation:'fixture',seq:1,source:'manual',ts:1000,ttl_ms:500,request_id:'fixture'};}}});
  await tasks.change({name:'fixture-task',can_move:true,motion_owner:'manual',option_schema:{field:'mode',default:'fixture',end_value:'stop'}},true);
  assert.deepEqual(events,['envelope','dispatch','queued-epoch-change']);
});

test('final safety settings check, envelope and dispatch precede queued STOP epoch change',async()=>{
  const events=[];
  const f=await fixture('safety.js',{replacements:{'transport.js':{
    request:async()=>{events.push('dispatch');return {status:202,data:{pending:true}};},
    poll:()=>({refresh(){}}),prepareMutation:async()=>{},
  }}});
  const panel=safetyOf(f);let pulses=0;
  panel.state={arming_mode:'lease',generation:'fixture-generation'};
  panel.prepare=async()=>{};
  panel.controls={state:{revision:1},refresh:async()=>{},pulse(direction){
    if(++pulses===2){
      events.push('settings-confirmed');
      Promise.resolve().then(()=>{panel.toggleEpoch++;panel.state=null;events.push('queued-stop-epoch');});
    }
    return {direction,device_settings:true,settings_revision:1};
  }};
  panel.envelope=(action,params)=>{
    events.push('envelope');
    assert.equal(panel.toggleEpoch,0);
    assert.equal(panel.state.generation,'fixture-generation');
    return {...params,action,request_id:'fixture'};
  };
  await panel.send('move',{direction:'forward'});
  assert.deepEqual(events,['settings-confirmed','envelope','dispatch','queued-stop-epoch']);
  assert.equal(panel.toggleEpoch,1);
});


test('safety dispatch keeps the original prepare completion continuation before queued STOP',async()=>{
  const events=[];
  const f=await fixture('safety.js',{replacements:{'transport.js':{
    request:async()=>{events.push('dispatch');return {status:202,data:{pending:true}};},
    poll:()=>({refresh(){}}),prepareMutation:async()=>{},
  }}});
  const panel=safetyOf(f);
  f.context.stopFixture=()=>{panel.toggleEpoch++;events.push('queued-stop-epoch');};
  // Same-realm fixture Promise avoids introducing cross-realm await assimilation.
  panel.prepare=vm.runInContext("() => { const ready=Promise.resolve(); ready.then(()=>Promise.resolve().then(()=>stopFixture())); return ready; }",f.context);
  panel.envelope=(action,params)=>{
    assert.equal(panel.toggleEpoch,0);
    events.push('envelope');
    return {...params,action,request_id:'fixture'};
  };
  await panel.send('height',{height:90});
  assert.deepEqual(events,['envelope','dispatch','queued-stop-epoch']);
});
