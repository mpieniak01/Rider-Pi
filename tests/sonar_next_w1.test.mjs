import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {loadSource} from './helpers/source-module.mjs';

const assets=new URL('../web/assets/operator/',import.meta.url);
const model=await loadSource(new URL('model.js',assets));
const calibration=await loadSource(new URL('calibration-model.js',assets));
const contract=await loadSource(new URL('contract.js',assets));
const {MjpegParser}=await loadSource(new URL('mjpeg.js',assets));
const plain=value=>JSON.parse(JSON.stringify(value));
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function element(tag='div',className='',text=''){
  const nodes=new Map();
  return {tag,nodeType:1,className,textContent:text,children:[],dataset:{},value:'',attributes:new Map(),
    classList:{toggle(){},add(){},remove(){}},
    append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},
    addEventListener(){},setAttribute(key,value){this.attributes.set(key,value);},removeAttribute(){},
    querySelector(selector){if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector);},
    querySelectorAll:()=>[],closest(){return this;},before(){},after(){}};
}
async function fixture(file,{request,modules={},globals={}}={}){
  const calls=[],messages=new Map(),nodes=new Map(),pills=[],entries=[];
  const node=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const context=vm.createContext({
    document:{getElementById:node,querySelectorAll:()=>[],createElement:element,hidden:false,
      documentElement:{lang:'en'},addEventListener(){},activeElement:null},
    window:{addEventListener(){}},sessionStorage:{getItem:()=>null,setItem(){}},
    setTimeout:()=>1,clearTimeout(){},setInterval:()=>2,clearInterval(){},AbortController,Headers,Blob,TextEncoder,TextDecoder,
    ...globals,
  });
  const replacements={
    'model.js':model,'request-id.js':{requestId:()=> 'w1-fixture'},
    'held-motion.js':{HeldMotion:class{}},
    'camera-power.js':{CameraPower:class{}},
    'camera-pipeline.js':{CameraPipelineControls:class{},PipelinePreview:class{update(){}}},
    'transport.js':{request:async(path,options={})=>{
      calls.push({path,...plain(options)});return request?request(path,options):{data:{ok:true},status:200};
    },poll:()=>({stop(){},refresh(){}}),prepareMutation:async()=>{}},
    'ui.js':{el:element,tr:(_pl,en)=>en,text:(id,value)=>messages.set(id,value),showError:error=>{throw error;},
      freshPill:(row,label,tone)=>{pills.push({row,label,tone});return element();},
      pill:()=>element(),kv:values=>{entries.push(...values);return element();},
      statusLabel:String,button:()=>element(),ageLabel:()=>'',ageStamp:()=>element(),rawDetails:()=>element(),details:()=>element(),
      powerLabel:value=>value===true?'ON':value===false?'OFF':'Unknown'},
    ...modules,
  };
  const root=new URL(file,assets),cache=new Map();
  async function at(value){
    const url=new URL(value);url.search='';
    if(!cache.has(url.href))cache.set(url.href,(async()=>{
      const replacement=url.href===root.href?null:replacements[url.pathname.split('/').at(-1)];
      if(replacement)return new vm.SyntheticModule(Object.keys(replacement),function(){
        for(const [key,value] of Object.entries(replacement))this.setExport(key,value);
      },{context,identifier:url.href});
      return new vm.SourceTextModule(await readFile(url,'utf8'),{context,identifier:url.href});
    })());
    return cache.get(url.href);
  }
  const loaded=await at(root);await loaded.link((specifier,parent)=>at(new URL(specifier,parent.identifier)));
  await loaded.evaluate();
  return {namespace:loaded.namespace,calls,messages,node,nodes,pills,entries,context};
}

test('remote stop preserves STOP, navigation-end, perception-end order with no overlapping requests',async()=>{
  let stopDone,firstDone;
  const stopped=new Promise(resolve=>{stopDone=resolve;});
  const first=new Promise(resolve=>{firstDone=resolve;});
  const f=await fixture('remote-navigation.js',{request:path=>path.endsWith('s14_venom_navigation')?first:{data:{ok:true}}});
  const panel=Object.create(f.namespace.RemoteNavigation.prototype);
  panel.safety={stop:()=>stopped};
  const pending=panel.stop();
  assert.equal(f.calls.length,0);
  stopDone();await settle();
  assert.deepEqual(f.calls.map(row=>row.path),['/api/logic/feature/s14_venom_navigation']);
  firstDone({data:{ok:true}});await pending;
  assert.deepEqual(f.calls.map(row=>row.path),[
    '/api/logic/feature/s14_venom_navigation','/api/logic/feature/s15_venom_perception',
  ]);
  assert.ok(f.calls.every(row=>row.method==='POST'&&row.body.enabled===false));
  assert.match(f.messages.get('remote-state'),/Restart requires a new intent/);
});
test('remote stop failure halts later mutations and does not announce completion',async()=>{
  for(const point of ['stop','navigation']){
    const f=await fixture('remote-navigation.js',{request:()=>{throw new Error('end fixture');}});
    const panel=Object.create(f.namespace.RemoteNavigation.prototype);
    panel.safety={stop:()=>point==='stop'?Promise.reject(new Error('stop fixture')):Promise.resolve()};
    await assert.rejects(panel.stop(),/fixture/);
    assert.equal(f.calls.length,point==='stop'?0:1);assert.equal(f.messages.has('remote-state'),false);
  }
});
test('envelope failure always rerenders but only a nonexempt command releases mutation ownership',async()=>{
  const f=await fixture('safety.js',{modules:{'request-id.js':{requestId:()=>{throw new Error('id fixture');}}}});
  for(const exempt of [false,true]){
    const panel=Object.create(f.namespace.SafetyPanel.prototype);let rendered=0;
    Object.assign(panel,{mutating:true,render:()=>rendered++,envelope:()=>{throw new Error('envelope fixture');}});
    assert.throws(()=>panel.commandForSend('stop',{},'manual',exempt),/fixture/);
    assert.equal(rendered,1);assert.equal(panel.mutating,exempt);assert.equal(f.calls.length,0);
  }
});
test('global toggle retains unknown armed stop intent and labels stale observations honestly',async()=>{
  const f=await fixture('safety.js'),panel=Object.create(f.namespace.SafetyPanel.prototype);
  Object.assign(panel,{now:()=>1000,lastArmed:true,clockReady:true,mutating:false,toggling:false,observationFailed:true});
  panel.state=null;panel.renderGlobalToggle();
  assert.equal(f.node('global-motion-toggle').textContent,'Arming state unknown');
  assert.match(f.node('global-motion-toggle').title,/stop and disarm/);
  panel.state={contract_version:1,state:'ARMED',observed_at:900};panel.renderGlobalToggle();
  assert.equal(f.node('global-motion-toggle').textContent,'Robot armed · last known state');
  assert.equal(f.node('global-motion-toggle').disabled,false);assert.equal(f.calls.length,0);
});
test('UI helpers keep parameter order, strict Boolean power labels and the element-versus-text branch',async()=>{
  const f=await fixture('ui.js');
  assert.equal(f.namespace.el('div').className,'');
  assert.equal(f.namespace.el('p',undefined,0).textContent,'0');
  assert.equal(f.namespace.el('p','fixture',false).textContent,'false');
  assert.equal(f.namespace.powerLabel(true),'ON');assert.equal(f.namespace.powerLabel(false),'OFF');
  for(const unknown of [null,undefined,0,1,'true'])assert.equal(f.namespace.powerLabel(unknown),'Unknown');
  const child=element('strong');
  const list=f.namespace.kv([['Zero',0],['Element',child]]);
  assert.equal(list.children[1].textContent,'0');assert.equal(list.children[3].children[0],child);
});
test('camera timestamps retain explicit null over mtime and file-time provenance stays distinct',()=>{
  const explicit=model.cameraFrame({raw:{exists:true,observed_at:null,mtime:999}},'raw',1000);
  assert.equal(explicit.ts,null);assert.equal(explicit.fresh,false);
  const legacy=model.cameraFrame({raw:{exists:true,mtime:997}},'raw',1000);
  assert.equal(legacy.ts,997);assert.equal(legacy.fresh,true);
  const file=model.cameraFrame({raw:{exists:true,observed_at:null,mtime:999,file_observed_at:998,provenance:'file_mtime'}},'raw',1000);
  assert.equal(file.ts,998);assert.equal(file.time_basis,'file_mtime');
  assert.equal(model.cameraFrame({raw:{exists:true,mtime:996.999}},'raw',1000).fresh,false);
});
test('trial averages preserve signed physical units and reject unknown trial kinds',()=>{
  assert.equal(calibration.trialAverage({kind:'linear',distance_m:-1,duration_s:2}),-.5);
  assert.equal(calibration.trialAverage({kind:'turn',angle_rad:3,duration_s:2}),1.5);
  assert.equal(calibration.trialAverage({kind:'other',distance_m:1,duration_s:1}),null);
  assert.equal(calibration.trialAverage({kind:'linear',distance_m:1,duration_s:0}),null);
});
function motionOutput(){
  return {contract_version:1,uart_owner:'motion-executor',instance_id:'i',generation:'g',hardware_ready:true,observed_at:1000,
    sdk_output:{source:'motion-executor',instance_id:'i',generation:'g',observed_at:1000,
      linear_step:0,turn_step:0,stopped:true,accepted:true}};
}
test('SDK output boundary preserves observed, stale and unconfirmed distinctions without fabricating completion',()=>{
  const source=motionOutput();
  assert.equal(calibration.sdkOutputObservation(source,1000.25).status,'observed');
  const stale=calibration.sdkOutputObservation(source,1000.25001);
  assert.equal(stale.ready,false);assert.equal(stale.status,'stale');assert.equal(stale.error,'sdk_output_stale');
  assert.equal(stale.linear_step,0);assert.equal(stale.physical_completion,'unverified');
  source.sdk_output.generation='other';
  const invalid=calibration.sdkOutputObservation(source,1000);
  assert.equal(invalid.status,'unknown');assert.equal(invalid.error,'sdk_output_unconfirmed');assert.equal(invalid.linear_step,null);
});
test('contract errors retain string, message, code and caller-fallback precedence',()=>{
  assert.equal(contract.errorMessage('wire'),'wire');
  assert.equal(contract.errorMessage({message:'message',code:'code'}),'message');
  assert.equal(contract.errorMessage({code:'code'}),'code');
  assert.equal(contract.errorMessage(null,'fallback'),'fallback');
  assert.equal(contract.errorMessage({},'fallback'),'fallback');
});
test('MJPEG decimal length remains ASCII bounded and trailing JPEG bytes use typed-array relative indexing',()=>{
  const parser=new MjpegParser('multipart/x-mixed-replace; boundary=w1');
  for(const invalid of ['0','01','١٢','1.0','99999999']){
    const headers=new Map([['content-length',invalid],['content-type','image/jpeg']]);
    assert.throws(()=>parser.imageLength(headers),/stream_/);
  }
  assert.equal(parser.imageLength(new Headers({'content-length':'4','content-type':'image/jpeg'})),4);
  parser.buffer=new Uint8Array([255,216,255,217,13,10]);
  assert.deepEqual(parser.readImage(0,4),new Uint8Array([255,216,255,217]));
  parser.buffer=new Uint8Array([255,216,0,0,13,10]);
  assert.throws(()=>parser.readImage(0,4),/stream_jpeg/);
});
test('history gap drawing starts a new pen and retains empty and nonempty relative timestamp summaries',async()=>{
  const f=await fixture('overview.js'),overview=Object.create(f.namespace.Overview.prototype),events=[];
  const ctx={beginPath(){},stroke(){},fillText(){},moveTo:()=>events.push('move'),lineTo:()=>events.push('line')};
  overview.axes=()=>({ctx,x:0,y:0,width:60,height:100});
  const summary=overview.drawHistory({hist_cpu:[10,20,30],hist_ts:[996,997,1000]},0,1000);
  assert.deepEqual(events,['move','line','move']);
  assert.deepEqual(plain(summary),{count:3,span:4,gaps:true});
  assert.deepEqual(plain(overview.drawHistory({},0,1000)),{count:0,span:0,gaps:false});
});
test('posture false, unknown and dirty values remain distinct and rendering sends no commands',async()=>{
  const f=await fixture('posture.js'),panel=Object.create(f.namespace.Posture.prototype);
  Object.assign(panel,{dirty:new Set(),root:element(),height:element(),balance:element()});
  panel.renderValues(90,false);assert.equal(panel.balance.value,'0');assert.equal(panel.height.value,90);
  panel.renderValues(90,null);assert.equal(panel.balance.value,'');
  panel.balance.value='1';panel.dirty.add('balance');panel.renderValues(90,false);
  assert.equal(panel.balance.value,'1');assert.equal(f.calls.length,0);
});
test('task badges and motion labels never infer actuator permission from an unknown field',async()=>{
  const f=await fixture('tasks.js',{modules:{'model.js':{...model,catalogKnown:()=>true,taskCanStart:()=>false}}});
  const tasks=Object.create(f.namespace.Tasks.prototype);
  Object.assign(tasks,{target:element(),catalog:{features:[true,false,undefined].map((can_move,index)=>({
    name:'task-'+index,can_move,state:'ready',ready:index!==2,error:index===2?'fixture error':null,
  }))},filter:()=>true,busy:new Set(),options:new Map(),results:new Map(),
    safety:{state:{},can:()=>false},choice:()=>null});
  tasks.render();
  assert.deepEqual(f.pills.map(row=>row.tone),['ok','ok','err']);
  assert.deepEqual(f.entries.filter(row=>row[0]==='Motion').map(row=>row[1]),[
    'YES — separate consent','no actuators','unknown — start blocked',
  ]);
  assert.equal(f.calls.length,0);
});
test('static camera fields are initialized per instance before any passive DOM lifecycle work',async()=>{
  const f=await fixture('devices.js');
  const first=new f.namespace.Devices(),second=new f.namespace.Devices();
  assert.equal(first.preview,false);assert.equal(first.imageBusy,false);assert.equal(first.telemetryUnavailable,true);
  first.resourceRows.push('fixture');assert.deepEqual(plain(second.resourceRows),[]);
  const controls=await fixture('camera-pipeline.js');
  const a=new controls.namespace.CameraPipelineControls(element()),b=new controls.namespace.CameraPipelineControls(element());
  assert.equal(a.status,null);assert.equal(a.busy,false);assert.equal(a.readEpoch,0);
  a.status={fixture:true};assert.equal(b.status,null);
  assert.equal(f.calls.length,0);assert.equal(controls.calls.length,0);
});
