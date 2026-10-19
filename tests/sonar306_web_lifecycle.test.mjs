import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const assets=new URL('../web/assets/',import.meta.url);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const plain=value=>JSON.parse(JSON.stringify(value));

async function sourceFixture(path,context,replacements){
  const cache=new Map();
  async function at(url){
    if(!cache.has(url.href))cache.set(url.href,(async()=>{
      const replacement=replacements[url.pathname.split('/').at(-1)];
      if(replacement)return new vm.SyntheticModule(Object.keys(replacement),function(){
        for(const [key,value] of Object.entries(replacement))this.setExport(key,value);
      },{context,identifier:url.href});
      return new vm.SourceTextModule(await readFile(url,'utf8'),{context,identifier:url.href});
    })());
    return cache.get(url.href);
  }
  const module=await at(new URL(path,assets));
  await module.link((specifier,parent)=>at(new URL(specifier,parent.identifier)));
  await module.evaluate();
  return module.namespace;
}

function domNode(){
  const listeners=new Map(),classes=new Set(),controls=new Map(),spans=new Map(),attributes=new Map();
  const node={listeners,classes,controls,spans,attributes,children:[],value:'',textContent:'',
    classList:{add:value=>classes.add(value),remove:value=>classes.delete(value)},
    addEventListener:(event,handler)=>listeners.set(event,handler),
    setAttribute:(key,value)=>attributes.set(key,value),
    appendChild(child){this.children.push(child);},
    querySelector:selector=>spans.get(selector)||null,
    querySelectorAll:selector=>{
      const action=selector.match(/data-action="([^"]+)"/)?.[1];
      return controls.has(action)?[controls.get(action)]:[];
    },
    fire(event,value){if(value!==undefined)this.value=value;return listeners.get(event)?.({target:this});},
  };
  Object.defineProperty(node,'innerHTML',{
    get(){return this.html??this.textContent.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');},
    set(html){
      this.html=html;this.children=[];
      for(const match of html.matchAll(/data-action="([^"]+)"/g)){
        const control=domNode();control.parentElement=node;controls.set(match[1],control);
      }
      for(const className of ['temp-value','brightness-value','color-temp-value']){
        const match=html.match(new RegExp('class="'+className+'">([^<]*)'));
        if(match)spans.set('.'+className,{textContent:match[1]});
      }
    },
  });
  return node;
}
const response=(body,{status=200,badJson=false}={})=>({
  ok:status>=200&&status<300,status,json:async()=>{if(badJson)throw new Error('fixture JSON');return body;},
});
const richDevice=()=>({name:'devices/<fixture>',type:'light',traits:{
  'sdm.devices.traits.OnOff':{on:false},
  'sdm.devices.traits.Brightness':{brightness:0},
  'sdm.devices.traits.ColorSetting':{temperatureK:3000,spectrumRgb:0x123456},
  'sdm.devices.traits.TemperatureSetting':{thermostatTemperatureSetpoint:21,thermostatTemperatureAmbient:19,
    availableThermostatModes:['off','heat'],thermostatMode:'heat'},
  'sdm.devices.traits.StartStop':{isRunning:true,isPaused:false},
  'sdm.devices.traits.Dock':{},
}});
async function homeFixture({devices=[richDevice()],authenticated=true,search='',route}={}){
  const nodes=new Map(),calls=[],timers=new Map(),events=new Map(),history=[],saved=[];
  const node=selector=>{if(!nodes.has(selector))nodes.set(selector,domNode());return nodes.get(selector);};
  const authButton=domNode();authButton.textContent='Authenticate';
  const state={authenticated,devices};
  let timerId=0;
  const context=vm.createContext({
    AbortController,URLSearchParams,navigator:{language:'en'},location:{search,pathname:'/google_home'},
    document:{querySelector:node,querySelectorAll:selector=>selector==='[data-auth-trigger]'?[authButton]:[],
      createElement:domNode,documentElement:{setAttribute:(key,value)=>saved.push([key,value])}},
    localStorage:{getItem:()=>null,setItem:(key,value)=>saved.push([key,value])},
    window:{addEventListener:(event,fn)=>events.set(event,fn),history:{replaceState:(...args)=>history.push(args)}},
    setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},clearTimeout:id=>timers.delete(id),
    fetch:async(path,options={})=>{
      calls.push({path,...options});
      const custom=await route?.(path,options,state);
      if(custom)return custom;
      if(path.endsWith('/status'))return response({authenticated:state.authenticated});
      if(path.endsWith('/devices'))return response({ok:true,devices:state.devices});
      if(path.endsWith('/auth')){state.authenticated=true;return response({ok:true});}
      if(path.endsWith('/command'))return response({ok:true});
      throw new Error('unexpected fixture request');
    },
  });
  await sourceFixture('google-home.js',context,{
    'i18n.js':{initI18n:async()=>{},applyDom(){},t:(key,values)=>key+(values?.msg?':'+values.msg:'')},
  });
  await settle();await settle();
  return {nodes,node,calls,timers,authButton,state,events,history,saved};
}

test('Google Home trait handlers send exact payloads only after explicit events and refresh after success',async()=>{
  const f=await homeFixture(),card=f.node('#devicesList').children[0];
  assert.equal(f.calls.filter(row=>row.method==='POST').length,0);
  assert.match(card.innerHTML,/&lt;fixture&gt;/);
  assert.match(card.innerHTML,/RUNNING/);
  const actions=[
    ['on','click',undefined,'OnOff',{on:true}],
    ['off','click',undefined,'OnOff',{on:false}],
    ['brightness','change','37','BrightnessAbsolute',{brightness:37}],
    ['color-temp','change','4200','ColorAbsolute',{color:{temperatureK:4200}}],
    ['color-rgb','change','#abcdef','ColorAbsolute',{color:{spectrumRgb:0xabcdef}}],
    ['temp-up','click',undefined,'ThermostatTemperatureSetpoint',{thermostatTemperatureSetpoint:21.5}],
    ['temp-down','click',undefined,'ThermostatTemperatureSetpoint',{thermostatTemperatureSetpoint:20.5}],
    ['thermostat-mode','change','off','ThermostatSetMode',{thermostatMode:'off'}],
    ['start','click',undefined,'StartStop',{start:true}],
    ['stop','click',undefined,'StartStop',{start:false}],
    ['pause','click',undefined,'PauseUnpause',{pause:true}],
    ['dock','click',undefined,'Dock',{}],
  ];
  for(const [action,event,value,command,params] of actions){
    card.controls.get(action).fire(event,value);await settle();
    const request=f.calls.at(-1);
    assert.equal(request.path,'/api/home/command');
    assert.equal(request.headers['Content-Type'],'application/json');
    assert.deepEqual(JSON.parse(request.body),{deviceId:'devices/<fixture>',command:'action.devices.commands.'+command,params});
    assert.equal(f.node('#statusMsg').textContent,'home.command_success');
  }
  card.controls.get('brightness').fire('input','0');
  card.controls.get('color-temp').fire('input','2000');
  assert.equal(card.spans.get('.brightness-value').textContent,'0%');
  assert.equal(card.spans.get('.color-temp-value').textContent,'2000K');
  const refresh=[...f.timers.values()].find(row=>row.delay===1500);
  assert.ok(refresh);
  const before=f.calls.length;await refresh.fn();await settle();
  assert.equal(f.calls.length,before+1);assert.equal(f.calls.at(-1).path,'/api/home/devices');
});

test('Google Home command failure and invalid JSON show errors without scheduling device refresh',async()=>{
  for(const failure of [response({ok:false,error:'denied'}),response({error:'blocked'},{status:409}),response(null,{status:502,badJson:true})]){
    const f=await homeFixture({route:path=>path.endsWith('/command')?failure:null});
    f.node('#devicesList').children[0].controls.get('on').fire('click');await settle();
    assert.match(f.node('#statusMsg').textContent,/home.error_send_command:(denied|blocked|HTTP 502)/);
    assert.equal([...f.timers.values()].some(row=>row.delay===1500),false);
    assert.equal(f.node('#statusMsg').className,'c-status-msg err');
  }
});

test('Google Home authentication preserves explicit button intent and restores the button on success',async()=>{
  const f=await homeFixture({authenticated:false,search:'?lang=EN&auth=success'});
  assert.equal(f.calls.length,1);assert.equal(f.node('#authBadge').className,'c-pill warn');
  assert.equal(f.node('#devicesSection').classes.has('hidden'),true);
  assert.equal(f.history[0][2],'/google_home');assert.ok(f.saved.some(row=>row[0]==='lang'&&row[1]==='en'));
  const pending=f.authButton.fire('click');
  assert.equal(f.authButton.disabled,true);assert.equal(f.authButton.textContent,'meta.loading...');
  await pending;await settle();
  assert.equal(f.authButton.disabled,false);assert.equal(f.authButton.textContent,'Authenticate');
  assert.equal(f.node('#authBadge').className,'c-pill ok');
  assert.equal(f.calls.filter(row=>row.path.endsWith('/auth')).length,1);
  assert.equal([...f.timers.values()].some(row=>row.delay===120000),false);
  f.events.get('dashboard:langchange')({detail:{lang:'pl'}});
  assert.ok(f.saved.some(row=>row[0]==='lang'&&row[1]==='pl'));
});

test('Google Home auth rejection and timeout restore the button and expose their distinct error messages',async()=>{
  const rejected=await homeFixture({authenticated:false,route:path=>path.endsWith('/auth')?response(null,{status:401,badJson:true}):null});
  await rejected.authButton.fire('click');
  assert.match(rejected.node('#statusMsg').textContent,/home.error_auth:Authentication failed/);
  assert.equal(rejected.authButton.disabled,false);
  const timed=await homeFixture({authenticated:false,route:(path,options)=>{
    if(!path.endsWith('/auth'))return null;
    return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{
      const error=new Error('fixture timeout');error.name='AbortError';reject(error);
    }));
  }});
  const pending=timed.authButton.fire('click');await settle();
  [...timed.timers.values()].find(row=>row.delay===120000).fn();
  await pending;
  assert.equal(timed.node('#statusMsg').textContent,'home.error_timeout');
  assert.equal(timed.authButton.textContent,'Authenticate');assert.equal(timed.authButton.disabled,false);
});

test('Google Home read failures, empty lists and refresh errors retain honest unavailable state',async()=>{
  const denied=await homeFixture({route:path=>path.endsWith('/status')?response({error:'offline'},{status:503}):null});
  assert.equal(denied.node('#authBadge').className,'c-pill err');
  assert.match(denied.node('#statusMsg').textContent,/home.error_check_auth:offline/);
  assert.equal(denied.calls.length,1);
  const empty=await homeFixture({devices:[]});
  assert.match(empty.node('#devicesList').innerHTML,/home.no_devices/);
  empty.state.devices=[{}];await empty.node('#btnRefresh').fire('click');await settle();
  assert.match(empty.node('#devicesList').children[0].innerHTML,/Unknown Device/);
  const failed=await homeFixture({route:path=>path.endsWith('/devices')?response({ok:false,error:'fixture missing'}):null});
  assert.match(failed.node('#devicesList').innerHTML,/home.error_load_devices:fixture missing/);
});

async function cameraFixture({taskName='s2_camera_preview',pipelineProcessing=false,pipeline=null,requested=false,options={},request}={}){
  const calls=[],errors=[],messages=new Map(),nodes=new Map(),events=new Map(),polls=[];
  const state={pipeline,catalog:{known:true,features:[{name:taskName,can_move:false,requested,ready:requested}],
    resource_states:{camera:{on:requested,service_running:true,data_fresh:false}}}};
  const node=id=>{if(!nodes.has(id))nodes.set(id,domNode());return nodes.get(id);};
  let cleared=0,started=0,stopped=0;
  const context=vm.createContext({
    document:{getElementById:node},window:{addEventListener:(event,fn)=>events.set(event,fn)},
    setInterval:()=>99,clearInterval:id=>{assert.equal(id,99);cleared++;},
  });
  const namespace=await sourceFixture('operator/camera-power.js',context,{
    'request-id.js':{requestId:prefix=>prefix+'-fixture'},
    'model.js':{catalogKnown:catalog=>catalog?.known===true,fresh:task=>task?.stale!==true,
      taskCanStart:task=>task?.available!==false},
    'ui.js':{text:(id,value)=>messages.set(id,value),tr:(_pl,en)=>en,showError:error=>errors.push(error),
      powerLabel:value=>value===true?'ON':value===false?'OFF':'Unknown'},
    'transport.js':{
      request:async(path,options={})=>{
        calls.push({path,...plain(options)});
        const custom=await request?.(path,options,state);if(custom)return custom;
        if(path==='/api/logic/catalog')return {data:state.catalog};
        if(path==='/api/resource/camera/pipeline'&&!options.method){
          if(state.pipeline)return {data:state.pipeline};
          throw Object.assign(new Error('fixture unsupported'),{status:404});
        }
        if(path==='/api/resource/camera/pipeline'){
          state.pipeline={...state.pipeline,ok:true,revision:state.pipeline.revision+1,
            state:options.body.action==='start'?'active':options.body.action==='stop'?'stopped':state.pipeline.state,
            profile:options.body.profile||state.pipeline.profile};
          return {data:state.pipeline};
        }
        if(path.startsWith('/api/logic/feature/')){
          state.catalog.features[0].requested=options.body.enabled;
          return {data:{ok:true}};
        }
        throw new Error('unexpected fixture request');
      },
      poll:(callback,options)=>{
        const poller={callback,options,refreshes:0,stops:0,refresh(){this.refreshes++;},stop(){this.stops++;}};
        polls.push(poller);return poller;
      },
    },
  });
  const panel=new namespace.CameraPower({taskName,pipelineProcessing,options,
    onStarted:()=>started++,onStopped:()=>stopped++});
  return {panel,state,calls,errors,messages,node,events,polls,get cleared(){return cleared;},
    get started(){return started;},get stopped(){return stopped;}};
}
const pipelineState=(changes={})=>({contract_id:'rider.camera_pipeline',contract_version:1,
  revision:3,state:'stopped',profile:{analysis_location:'pc',local_engine:'none'},
  capabilities:{analysis_locations:['pc','local']},...changes});

test('camera polling is read only, unsupported pipeline falls back to explicit task changes and pagehide stops timers',async()=>{
  const f=await cameraFixture({options:{fixture:'kept'}});
  assert.equal(f.calls.length,0);assert.equal(f.node('camera-toggle').disabled,true);
  await f.polls[0].callback();
  assert.ok(f.calls.every(row=>!row.method));assert.equal(f.node('camera-start').disabled,false);
  await f.panel.change(true);
  const mutation=f.calls.find(row=>row.method==='POST');
  assert.equal(mutation.path,'/api/logic/feature/s2_camera_preview');
  assert.deepEqual(mutation.body,{enabled:true,options:{fixture:'kept'}});
  assert.equal(f.started,1);assert.equal(f.panel.busy,false);assert.equal(f.polls[0].refreshes,1);
  await f.node('camera-toggle').fire('click');
  assert.equal(f.stopped,1);
  f.events.get('pagehide')();assert.equal(f.polls[0].stops,1);assert.equal(f.cleared,1);
});

test('camera fresh recheck blocks stale, movable, duplicate and unsupported start states before POST',async()=>{
  for(const patch of [{stale:true},{can_move:true},{requested:true},{available:false}]){
    const f=await cameraFixture();Object.assign(f.state.catalog.features[0],patch);
    await f.panel.change(true);
    assert.equal(f.calls.filter(row=>row.method).length,0);
    assert.equal(f.errors.length,1);assert.equal(f.panel.catalog,null);assert.equal(f.panel.busy,false);
  }
  const f=await cameraFixture({pipeline:pipelineState({state:'waiting_frame'})});
  await f.panel.change(true);
  assert.equal(f.calls.filter(row=>row.method).length,0);assert.equal(f.errors.length,1);
});

test('camera pipeline uses returned configuration revision for explicit local start and stop',async()=>{
  const f=await cameraFixture({taskName:'s7_obstacle_module',pipelineProcessing:true,pipeline:pipelineState()});
  await f.panel.change(true);
  const posts=f.calls.filter(row=>row.method);
  assert.deepEqual(posts.map(row=>row.body.action),['configure','start']);
  assert.equal(posts[0].body.expected_revision,3);assert.equal(posts[1].body.expected_revision,4);
  assert.deepEqual(posts[0].body.profile,{analysis_location:'local',local_engine:'canny'});
  assert.equal(f.panel.task().ready,true);assert.equal(f.started,1);
  await f.panel.change(false);
  assert.equal(f.calls.filter(row=>row.method).at(-1).body.action,'stop');
  assert.equal(f.stopped,1);assert.equal(f.errors.length,0);
});

test('obstacle task-only operation configures local analysis but preserves shared pipeline running state',async()=>{
  const f=await cameraFixture({taskName:'s7_obstacle_module',pipeline:pipelineState()});
  await f.panel.change(true);
  const posts=f.calls.filter(row=>row.method);
  assert.equal(posts.length,2);assert.equal(posts[1].path,'/api/logic/feature/s7_obstacle_module');
  assert.equal(f.state.pipeline.state,'stopped');assert.equal(f.started,1);
  assert.equal(f.panel.task().requested,true);
});

test('camera rejected configure, pipeline start and task responses stop callbacks and release busy lock',async()=>{
  for(const stage of ['configure','start','task']){
    const f=await cameraFixture({taskName:stage==='configure'?'s7_obstacle_module':'s2_camera_preview',
      pipelineProcessing:stage==='configure',pipeline:stage==='task'?null:pipelineState(),
      request:(path,options)=>{
        if(options.method&&((stage==='task'&&path.startsWith('/api/logic/feature/'))||options.body.action===stage))
          return {data:{ok:false,error:'fixture rejected '+stage}};
        return null;
      }});
    await f.panel.change(true);
    assert.match(f.errors[0].message,/fixture rejected/);assert.equal(f.panel.busy,false);
    assert.equal(f.started,0);assert.equal(f.polls[0].refreshes,1);
    assert.equal(f.calls.filter(row=>row.method).length,1);
  }
});

test('camera duplicate click while loading never sends another request and propagated read errors remain unknown',async()=>{
  let finish;
  const gate=new Promise(resolve=>{finish=resolve;});
  const f=await cameraFixture({request:async path=>{
    if(path==='/api/logic/catalog')await gate;
    return null;
  }});
  const first=f.panel.change(true);await f.panel.change(true);
  assert.equal(f.calls.length,1);assert.equal(f.node('camera-toggle').disabled,true);
  finish();await first;
  assert.equal(f.calls.filter(row=>row.method).length,1);
  const failed=await cameraFixture({request:path=>{
    if(path==='/api/resource/camera/pipeline')throw Object.assign(new Error('fixture unavailable'),{status:503});
    return null;
  }});
  await failed.panel.change(true);
  assert.equal(failed.calls.filter(row=>row.method).length,0);
  assert.equal(failed.errors[0].message,'fixture unavailable');
  failed.polls[0].options.onError(new Error('poll fixture'));
  assert.equal(failed.panel.catalog,null);assert.match(failed.messages.get('camera-power-state'),/Unknown/);
});

test('camera shared resource notes retain stale power uncertainty and task errors without claiming fresh frames',async()=>{
  const f=await cameraFixture();
  f.state.catalog.features.push({name:'other',title_en:'Other fixture',requested:true,resources:['camera']});
  f.state.catalog.features[0].start_available=false;
  f.state.catalog.features[0].start_unavailable_reason='not ready';
  f.state.catalog.resource_states.camera.stale=true;
  await f.panel.load();
  const message=f.messages.get('camera-power-state');
  assert.match(message,/Unknown/);assert.match(message,/not ready/);assert.match(message,/Other fixture/);
  assert.match(message,/process still running/);assert.match(message,/No fresh frames/);
  f.state.catalog.features[0].error='preview fixture failed';f.panel.render();
  assert.match(f.messages.get('camera-power-state'),/Camera error: preview fixture failed/);
});
