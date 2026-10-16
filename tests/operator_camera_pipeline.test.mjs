import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';
const root = new URL('../', import.meta.url);
const assets = new URL('web/assets/operator/', root);
const moduleOf = async file => import('data:text/javascript;base64,' + Buffer.from(await readFile(new URL(file, assets))).toString('base64'));
const {MjpegParser, readMjpeg} = await moduleOf('mjpeg.js');
const {decodeResponse, responseFamily} = await moduleOf('contract.js');
const fixture = JSON.parse(await readFile(new URL('config/contracts/camera_pipeline_v1.examples.json', root)));
const encode = value => new TextEncoder().encode(value);
const jpeg = new Uint8Array([255,216,1,2,255,217]);
const packet = new Uint8Array([...encode('--pi\r\nContent-Type: image/jpeg\r\nContent-Length: 6\r\nX-Rider-Source: '+JSON.stringify(fixture.source)+'\r\n\r\n'),...jpeg,...encode('\r\n--pi--\r\n')]);
test('Pi and Venom wire examples decode through the existing negotiated panel contract', () => {
  const envelope = {ok:true, data:fixture.stopped_status, error:null, operation:null,
    meta:{envelope_version:1,contract_id:'rider.camera_pipeline',contract_version:1,server_time:1,observed_at:1}};
  const family = responseFamily('/api/resource/camera/pipeline');
  assert.equal(family,'rider.camera_pipeline');
  assert.deepEqual(decodeResponse(envelope,200,family).data.profile,fixture.stopped_status.profile);
});
test('native producer packet survives all network fragment positions and retains original capture metadata', () => {
  for (let split=1;split<packet.length;split++) {
    const parser = new MjpegParser('multipart/x-mixed-replace; boundary=pi');
    const frames = [...parser.feed(packet.slice(0,split)),...parser.feed(packet.slice(split))];
    parser.finish(); assert.equal(frames.length,1); assert.deepEqual(frames[0].bytes,jpeg);
    assert.deepEqual(JSON.parse(frames[0].headers.get('X-Rider-Source')),fixture.source);
  }
});
test('bad framing and pending reads cannot leak a partial or stale JPEG', async () => {
  const parser=new MjpegParser('multipart/x-mixed-replace; boundary=pi');
  parser.feed(packet.slice(0,40));assert.throws(()=>parser.finish(),/truncated/);
  let cancelled=false, frames=0;
  const stream=new ReadableStream({start(c){c.enqueue(packet.slice(0,20));},cancel(){cancelled=true;}});
  const abort=new AbortController();
  const done=readMjpeg(new Response(stream,{headers:{'Content-Type':'multipart/x-mixed-replace; boundary=pi'}}),abort.signal,()=>frames++);
  await new Promise(resolve=>setImmediate(resolve));abort.abort();await done;
  assert.equal(cancelled,true);assert.equal(frames,0);
});
const previewSource=(await readFile(new URL('camera-pipeline.js',assets),'utf8'))
  .replace(/^import .*;$/gm,'').replace('export function validPipeline','function validPipeline')
  .replace('export class CameraPipelineControls','class CameraPipelineControls')
  .replace('export class PipelinePreview','globalThis.PipelinePreview=class PipelinePreview');
test('Pi preview refuses old epochs and applies clockwise rotation before flips without camera or model calls', async () => {
  const calls=[], urls=[];
  const canvas={style:{},setAttribute(){},getContext(){return {translate(...x){calls.push(['translate',...x]);},scale(...x){calls.push(['scale',...x]);},rotate(...x){calls.push(['rotate',...x]);},drawImage(){calls.push(['draw']);}};}};
  const context=vm.createContext({
    document:{createElement(){return canvas;},addEventListener(){},hidden:false},
    window:{addEventListener(){}},setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){},
    tr:pl=>pl,performance:{now:()=>10},Blob,URL:{createObjectURL(){return 'blob:fixture';},revokeObjectURL(url){urls.push(url);}},
    Image:class{width=320;height=240;async decode(){}},console,
  });
  vm.runInContext(previewSource,context);
  const image={hidden:false,after(){},dataset:{},removeAttribute(){}}, label={}, empty={};
  const preview=new context.PipelinePreview(image,{status:label,empty});
  preview.profile={revision:fixture.source.pipeline_revision,transport_epoch:fixture.source.transport_epoch,camera_session:fixture.source.camera_session};
  const part={bytes:jpeg,headers:new Headers({'X-Rider-Source':JSON.stringify({...fixture.source,frame_age_ms:20,image_transform:{rotation:90,flip_h:true,flip_v:false}})}),receivedAt:10};
  await preview.display(part,new AbortController().signal,()=>true);
  assert.equal(canvas.width,240);assert.equal(canvas.height,320);
  assert.deepEqual(calls,[['translate',120,160],['scale',-1,1],['rotate',Math.PI/2],['draw']]);
  assert.equal(empty.hidden,true);assert.deepEqual(urls,['blob:fixture']);
  part.headers.set('X-Rider-Source',JSON.stringify({...fixture.source,transport_epoch:fixture.source.transport_epoch+1}));
  await assert.rejects(preview.display(part,new AbortController().signal,()=>true),/source_mismatch/);
  assert.equal(calls.length,4);
});

test('legacy observation stays on its compatible preview until explicit upgrade', () => {
  const context = vm.createContext({document:{createElement(){return {style:{},setAttribute(){}};},addEventListener(){}},
    window:{addEventListener(){}},setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){},tr:pl=>pl});
  vm.runInContext(previewSource,context);
  const image={dataset:{},after(){}};
  const preview=new context.PipelinePreview(image);
  preview.update({...fixture.stopped_status,state:'active',compatibility_mode:'legacy'});
  assert.equal(preview.profile,undefined);
  assert.equal(image.dataset.pipelineManaged,undefined);
});

test('late GET cannot replace the profile confirmed by POST; busy polls are skipped', async () => {
  let completeRead, calls=0;const observed=[];
  const next={...fixture.stopped_status,revision:2,profile:{...fixture.stopped_status.profile,remote_transport:'mjpeg'}};
  const context=vm.createContext({request:async (path,options={})=>{
    calls++;return options.method==='POST'?{data:next}:new Promise(resolve=>completeRead=resolve);
  },showError(error){throw error;},console});
  vm.runInContext(previewSource+';globalThis.Controls=CameraPipelineControls;',context);
  const controls=Object.create(context.Controls.prototype);
  Object.assign(controls,{status:fixture.stopped_status,busy:false,readEpoch:0,onState:value=>observed.push(value),render(){},poller:{refresh(){}}});
  const old=controls.load();
  await controls.change('configure',next.profile);
  completeRead({data:fixture.stopped_status,received_at:1,sent_at:1});await old;
  assert.equal(controls.status.revision,2);
  controls.busy=true;await controls.load();assert.equal(calls,2);
  assert.equal(observed.filter(Boolean).at(-1).revision,2);
});
test('delayed network frame is expired by the Pi monotonic anchor before rendering', async () => {
  let drawn=0;
  const canvas={style:{},setAttribute(){},getContext(){drawn++;throw new Error('must not render stale network frame');}};
  const context=vm.createContext({document:{createElement(){return canvas;},addEventListener(){}},
    window:{addEventListener(){}},setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){},
    tr:pl=>pl,performance:{now:()=>2000}});
  vm.runInContext(previewSource,context);
  const preview=new context.PipelinePreview({after(){},dataset:{}});
  preview.profile={revision:fixture.source.pipeline_revision,transport_epoch:fixture.source.transport_epoch,camera_session:fixture.source.camera_session};
  preview.anchor={latest:{...fixture.source,frame_age_ms:1200},receivedAt:1990,roundTripMs:20};
  await preview.display({bytes:jpeg,receivedAt:2000,headers:new Headers({'X-Rider-Source':JSON.stringify({...fixture.source,frame_age_ms:10})})},new AbortController().signal,()=>true);
  assert.equal(drawn,0);
});
