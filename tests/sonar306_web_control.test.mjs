import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {loadSource} from './helpers/source-module.mjs';

const assets=new URL('../web/assets/operator/',import.meta.url);
const model=await loadSource(new URL('model.js',assets));
const contract=await loadSource(new URL('contract.js',assets));
const calibration=await loadSource(new URL('calibration-model.js',assets));
const {MjpegParser,readMjpeg}=await loadSource(new URL('mjpeg.js',assets));
const cameraExample=JSON.parse(await readFile(new URL('../config/contracts/camera_pipeline_v1.examples.json',import.meta.url),'utf8'));
const encode=value=>new TextEncoder().encode(value);
const jpeg=new Uint8Array([255,216,1,2,255,217]);
const part=(headers='Content-Type: image/jpeg\r\nContent-Length: 6',bytes=jpeg)=>
  new Uint8Array([...encode('--pi\r\n'+headers+'\r\n\r\n'),...bytes,...encode('\r\n')]);
const end=encode('--pi--\r\n');
const join=(...rows)=>new Uint8Array(rows.flatMap(row=>[...row]));

// Each screen loads its unchanged production source and imports into an isolated VM.
// Transport, timers and DOM are inert; no browser, robot, service or real fetch exists.
async function screen(file,{globals={},modules={}}={}) {
  const calls=[],messages=new Map(),listeners=new Map();
  const context=vm.createContext({
    AbortController,Headers,TextEncoder,TextDecoder,Uint8Array,Blob,structuredClone,
    document:{hidden:false,getElementById:()=>null,addEventListener(){},createElement:()=>({style:{},setAttribute(){}})},
    window:{addEventListener(name,fn){listeners.set(name,fn);}},
    setInterval:()=>1,clearInterval(){},setTimeout:()=>2,clearTimeout(){},
    performance:{now:()=>100},location:{hostname:'fixture'},...globals,
  });
  const replacements={
    'model.js':model,
    'transport.js':{request:async(path,options={})=>{calls.push({path,...options});throw new Error('unexpected_fixture_request');},
      poll:()=>({stop(){},refresh(){}})},
    'ui.js':{tr:(_pl,en)=>en,text:(id,value)=>messages.set(id,value),showError:error=>{throw error;},
      powerLabel:value=>value===true?'ON':value===false?'OFF':'Unknown',statusLabel:String,
      el:()=>({})},
    'request-id.js':{requestId:prefix=>prefix+'-fixture'},
    'devices.js':{telemetryChannel:()=>{throw new Error('unexpected_telemetry_fixture');}},...modules,
  };
  const cache=new Map();
  async function moduleAt(url) {
    url=new URL(url);url.search='';
    if(!cache.has(url.href))cache.set(url.href,(async()=>{
      const name=url.pathname.split('/').at(-1),replacement=replacements[name];
      if(replacement)return new vm.SyntheticModule(Object.keys(replacement),function(){
        for(const [key,value] of Object.entries(replacement))this.setExport(key,value);
      },{context,identifier:url.href});
      return new vm.SourceTextModule(await readFile(url,'utf8'),{context,identifier:url.href});
    })());
    return cache.get(url.href);
  }
  const loaded=await moduleAt(new URL(file,assets));
  await loaded.link((specifier,parent)=>moduleAt(new URL(specifier,parent.identifier)));
  await loaded.evaluate();
  return {namespace:loaded.namespace,calls,messages,listeners,context};
}

test('contract validation retains source metadata and permits HTTP errors only for failure status',()=>{
  const meta={envelope_version:1,contract_id:'rider.safety',contract_version:1,server_time:20,stale:true};
  const envelope={meta,ok:true,data:{server_time:10,observed_at:null},error:null};
  const decoded=contract.decodeResponse(envelope,200,'rider.safety');
  assert.equal(decoded.data.server_time,10);
  assert.equal(decoded.data.observed_at,null);
  assert.equal(decoded.data.stale,true);
  assert.equal(decoded.meta,meta);
  const http={...envelope,ok:false,meta:{...meta,contract_id:'rider.http'}};
  assert.throws(()=>contract.decodeResponse(http,200,'rider.safety'),/contract/);
  assert.equal(contract.decodeResponse(http,409,'rider.safety').canonical,true);
  assert.throws(()=>contract.decodeResponse({...envelope,meta:{...meta,contract_version:2}},409),/contract/);
});

test('MJPEG parser retains every coalesced frame through its bounded input slices',()=>{
  const large=new Uint8Array(65540);large.set([255,216]);large.set([255,217],large.length-2);
  const parser=new MjpegParser('multipart/x-mixed-replace; boundary="pi"');
  const frames=parser.feed(join(part('Content-Type: image/jpeg\r\nContent-Length: '+large.length,large),part(),end));
  parser.finish();
  assert.equal(frames.length,2);
  assert.deepEqual(frames[0].bytes,large);
  assert.deepEqual(frames[1].bytes,jpeg);
  assert.throws(()=>parser.feed(encode('x')),/stream_after_end/);
});

test('MJPEG framing rejects malformed headers, size and JPEG boundaries before offering data',()=>{
  const cases=[
    ['Content-Type: image/jpeg\r\nContent-Length: 6\r\ncontent-length: 6','duplicate_header',jpeg],
    ['InvalidHeader','stream_header',jpeg],
    ['Content-Type: image/jpeg\r\nContent-Length: 0','content_length',jpeg],
    ['Content-Type: image/jpeg\r\nContent-Length: 2097153','image_limit',jpeg],
    ['Content-Type: image/png\r\nContent-Length: 6','image_type',jpeg],
    ['Content-Type: image/jpeg\r\nContent-Length: 6','stream_jpeg',new Uint8Array(6)],
  ];
  for(const [headers,error,bytes] of cases){
    const parser=new MjpegParser('multipart/x-mixed-replace; boundary=pi');
    assert.throws(()=>parser.feed(part(headers,bytes)),new RegExp(error));
  }
  const headers=new MjpegParser('multipart/x-mixed-replace; boundary=pi');
  assert.throws(()=>headers.feed(encode('--pi\r\nX: '+'a'.repeat(17000))),/headers_limit/);
  const ending=new MjpegParser('multipart/x-mixed-replace; boundary=pi');
  ending.feed(encode('--pi--\r'));
  assert.throws(()=>ending.finish(),/truncated/);
  ending.feed(encode('\n'));ending.finish();
});

test('aborting on the first MJPEG offer prevents coalesced later offers and releases the reader',async()=>{
  const abort=new AbortController();let cancelled=0,released=0,removed=0,offers=0;
  const reader={read:async()=>({value:join(part(),part(),end),done:false}),
    cancel:async()=>{cancelled++;},releaseLock(){released++;}};
  const signal={get aborted(){return abort.signal.aborted;},
    addEventListener:(...args)=>abort.signal.addEventListener(...args),
    removeEventListener:(...args)=>{removed++;abort.signal.removeEventListener(...args);}};
  await readMjpeg({ok:true,headers:new Headers({'Content-Type':'multipart/x-mixed-replace; boundary=pi'}),
    body:{getReader:()=>reader}},signal,()=>{offers++;abort.abort();});
  assert.equal(offers,1);assert.equal(released,1);assert.equal(removed,1);assert.ok(cancelled>=1);
});

test('navigation inherits cache failures without promoting a planning refusal to geometry evidence',async()=>{
  const f=await screen('navigation.js'),nav=Object.create(f.namespace.Navigation.prototype);
  const child={observed_at:100,quality:'good',source:'mapper',width_cells:1,height_cells:1,grid:[0]};
  nav.observeSnapshot({map:child},{planning_only:true,data_error:'navigation_traversal_unverified'});
  assert.equal(nav.map.observed_at,100);assert.equal(nav.map.data_error,undefined);
  nav.observeSnapshot({map:child,data_error:'inner_failure'},{planning_only:true,data_error:'navigation_traversal_unverified'});
  assert.equal(nav.map.data_error,'inner_failure');
  nav.observeSnapshot({map:child,data_ready:false,quality:'unknown'},{offline:true,error:'transport_failure'});
  assert.equal(nav.map.offline,true);assert.equal(nav.map.error,'transport_failure');
  assert.equal(nav.map.data_ready,false);assert.equal(nav.map.quality,'unknown');
  assert.equal(nav.map.observed_at,100);
  nav.observeSnapshot(null);
  assert.equal(nav.map.stale,true);
});

test('passive navigation actions and invalid map dimensions never request or draw motion',async()=>{
  let gridDraws=0;
  const ctx={fillRect(){gridDraws++;}};
  const f=await screen('navigation.js'),nav=Object.create(f.namespace.Navigation.prototype);
  Object.assign(nav,{render(){},canvas:{clientWidth:600,getContext:()=>ctx},map:{width_cells:65537,height_cells:1,grid:[]}});
  await nav.command('start');await nav.command('return_home');
  nav.draw();
  assert.equal(f.calls.length,0);
  assert.equal(gridDraws,1); // Only the blank canvas is drawn; invalid geometry has no overlay.
  assert.match(f.messages.get('nav-request'),/passive_plan_request_unavailable/);
});

test('manual validation preserves zero-stop intent, pulse feasibility and error order',async()=>{
  const f=await screen('manual-settings.js'),panel=Object.create(f.namespace.ManualSettings.prototype);
  const directions=['forward','backward','left','right'];
  const row={speed:.2,duration:.25,minimum:0,maximum:.6,step:.01};
  const values={linear_rate:3,turn_rate:4,linear_deceleration:3,turn_deceleration:4,reversal_pause:0};
  Object.assign(panel,{state:{values,directions:Object.fromEntries(directions.map(name=>[name,{...row}])),parameter_schema:{}},
    pending:{},directionEdits:{},descriptor:key=>({minimum:key==='duration'?.01:0,maximum:key==='duration'?1:100}),
    range:()=> 'fixture range',format:(_key,value)=>String(value)});
  assert.equal(panel.validation().length,0);
  panel.directionEdits.forward={speed:0,minimum:.2,duration:.01};
  assert.deepEqual(Array.from(panel.validation(),row=>row.id),['setting-forward-minimum']);
  panel.directionEdits.forward={speed:.9,minimum:.7,maximum:.6,step:0,duration:0};
  assert.deepEqual(Array.from(panel.validation(),row=>row.id),[
    'setting-forward-duration','setting-forward-minimum','setting-forward-step',
    'setting-forward-speed','setting-forward-minimum']);
  assert.equal(f.calls.length,0);
});

test('overview late image errors cannot clear a newer confirmed frame',async()=>{
  const nodes=new Map(), image={dataset:{},getAttribute(){return this.src;}};
  nodes.set('img_cam',image);
  const f=await screen('overview.js',{globals:{document:{hidden:false,getElementById:id=>nodes.get(id)||null}},
    modules:{'model.js':{...model,cameraFrame:(_snap,kind)=>({exists:true,fresh:true,age:.1,ts:kind==='raw'?stamp:0})}}});
  let stamp=1;
  const overview=Object.create(f.namespace.Overview.prototype);
  Object.assign(overview,{health:{devices:{camera:{on:true}}},drawBins(){}});
  overview.renderVision();const lateError=image.onerror;
  assert.match(image.src,/\?v=1$/);
  stamp=2;overview.renderVision();lateError();
  assert.match(image.src,/\?v=2$/);
  image.onerror();
  assert.match(image.src,/^data:image/);
  assert.match(f.messages.get('leg_cam_txt'),/image read failed/);
  assert.equal(f.calls.length,0);
});

test('aborted decoded preview is discarded and its object URL revoked',async()=>{
  let finishDecode,drawn=0,revoked=0;
  const canvas={style:{},setAttribute(){},getContext(){drawn++;}};
  const f=await screen('camera-pipeline.js',{globals:{
    document:{hidden:false,createElement:()=>canvas,addEventListener(){}},
    Image:class{decode(){return new Promise(resolve=>{finishDecode=resolve;});}},
    URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){revoked++;}},
  }});
  const preview=new f.namespace.PipelinePreview({after(){},dataset:{}});
  const source={...cameraExample.source,frame_age_ms:0};
  preview.profile={revision:source.pipeline_revision,transport_epoch:source.transport_epoch,camera_session:source.camera_session};
  preview.anchor={latest:source,receivedAt:100,roundTripMs:0};
  const abort=new AbortController();
  const pending=preview.display({bytes:jpeg,receivedAt:100,headers:new Headers({'X-Rider-Source':JSON.stringify(source)})},abort.signal,()=>true);
  abort.abort();finishDecode();await pending;
  assert.equal(drawn,0);assert.equal(revoked,1);assert.equal(preview.shown,undefined);
});

test('preview drain has one owner and keeps only the newest pending frame',async()=>{
  const f=await screen('camera-pipeline.js'),preview=Object.create(f.namespace.PipelinePreview.prototype);
  let pending='first',busy=false,current=true,finishFirst;
  const drawn=[];
  preview.display=async frame=>{drawn.push(frame);if(frame==='first')await new Promise(resolve=>{finishFirst=resolve;});};
  const queue={busy:()=>busy,setBusy:value=>{busy=value;},current:()=>current,
    signal:new AbortController().signal,hasFrame:()=>Boolean(pending),take:()=>{const value=pending;pending=null;return value;}};
  const drain=preview.drainFrames(queue);
  pending='superseded';await preview.drainFrames(queue);pending='latest';
  finishFirst();await drain;
  assert.deepEqual(drawn,['first','latest']);assert.equal(busy,false);
  current=false;pending='after_close';await preview.drainFrames(queue);
  assert.deepEqual(drawn,['first','latest']);assert.equal(busy,false);
});

test('calibration preserves signed table boundaries and first failure before manual evidence',()=>{
  const profile=calibration.defaultProfile();profile.name='fixture';
  profile.odometry.linear_m_s={'127':.3,'-127':-.3};
  profile.odometry.turn_rad_s={'180':1,'-180':-1};
  assert.equal(calibration.profileError(profile),null);
  profile.odometry.manual_verified=true;
  profile.odometry.linear_m_s={'01':.3};
  assert.equal(calibration.profileError(profile),'invalid_signed_measurement');
  profile.odometry.linear_m_s={'127':.3};
  assert.equal(calibration.profileError(profile),'manual_measurement_evidence_required');
  profile.odometry.turn_rad_s={'181':1};
  assert.equal(calibration.profileError(profile),'invalid_signed_measurement');
});

test('preview final decoder continuation releases queue ownership before a later microtask offer',async()=>{
  const f=await screen('camera-pipeline.js'),preview=Object.create(f.namespace.PipelinePreview.prototype);
  const events=[];let busy=false,pending=true;
  const ready=vm.runInContext('Promise.resolve()',f.context);
  preview.display=()=>{
    events.push('display');
    ready.then(()=>Promise.resolve().then(()=>events.push(busy?'still-busy':'released')));
    return ready;
  };
  const queue={busy:()=>busy,setBusy:value=>{busy=value;events.push('busy:'+value);},
    current:()=>true,signal:new AbortController().signal,hasFrame:()=>pending,take:()=>{pending=false;return 'frame';}};
  const result=preview.drainFrames(queue);
  assert.deepEqual(events,['busy:true','display']);
  await result;await Promise.resolve();
  assert.deepEqual(events,['busy:true','display','busy:false','released']);
});

test('preview rejected decoder preserves current-only stale reporting and always releases its owner',async()=>{
  for(const cancelled of [false,true]){
    const f=await screen('camera-pipeline.js'),preview=Object.create(f.namespace.PipelinePreview.prototype);
    let busy=false,current=true,pending=true,stale=0;
    preview.stale=()=>{stale++;};
    preview.display=()=>{if(cancelled)current=false;return Promise.reject(new Error('fixture decode'));};
    const queue={busy:()=>busy,setBusy:value=>{busy=value;},current:()=>current,
      signal:new AbortController().signal,hasFrame:()=>pending,take:()=>{pending=false;return 'frame';}};
    await preview.drainFrames(queue);
    assert.equal(busy,false);assert.equal(stale,cancelled?0:1);
  }
});
