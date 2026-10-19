import {loadSource} from './helpers/source-module.mjs';
import { webcrypto } from 'node:crypto';
// No robot connections: task transport and timers are isolated fixtures.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';
const requestId = prefix => prefix + '-' + webcrypto.randomUUID();
const assets = new URL('../web/assets/operator/', import.meta.url);
const model=await loadSource(new URL('model.js',assets));
const source = (await readFile(new URL('camera-power.js', assets), 'utf8')).replace(/^import .*;$/gm, line => line.replace(/[^\n]/g, ' ')).replace('export class CameraPower', '       class CameraPower') + ';globalThis.CameraPower=CameraPower;';
function fixture(patch = {}, { stale = false, rejected = false, others = [], control = {}, activity = null, pipeline = null, configureRejected = false } = {}) {
  const now = Date.now() / 1000;
  const task = { name: 's2_camera_preview', can_move: false, installed: true, observed_at: now,
    state: 'stopped', requested: false, ready: false, ...patch };
  const catalog = { contract_version: 2, catalog_version: 2, observed_at: stale ? now - 30 : now, features: [task, ...others], units: [], resource_states: {camera: activity} };
  const calls = [], errors = [], messages = new Map(), buttons = new Map(['camera-start', 'camera-stop', 'camera-toggle', 'camera-proc-toggle', 'camera-obst-toggle', 'camera-tracker-toggle'].map(id => [id, { disabled: true, listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; }, setAttribute(name, value) { this[name] = value; } }]));
  let started = 0, stopped = 0;
  const context = vm.createContext({ requestId, ...model,
    document: { getElementById: id => buttons.get(id) }, window: { addEventListener() {} },
    setInterval: () => 1, clearInterval() {},
    powerLabel: value => value === true ? 'ON' : value === false ? 'OFF' : 'Nieznany',
    tr: pl => pl, text: (id, value) => messages.set(id, value), showError: error => errors.push(error),
    poll: () => ({ refresh() {}, stop() {} }),
    request: async (path, options = {}) => {
      calls.push({ path, ...options });
      if (path === '/api/resource/camera/pipeline' && pipeline) {
        if (options.method === 'POST') {
          if (options.body.action === 'configure') {
            if (configureRejected) return {data:{ok:false,error:'camera_pipeline_revision_conflict'}};
            pipeline.profile = options.body.profile; pipeline.revision++;
          }
          if (options.body.action === 'start') pipeline.state = 'active';
          if (options.body.action === 'stop') pipeline.state = 'stopped';
        }
        return {data:pipeline};
      }

      if (options.method === 'POST') {
        if (rejected) throw new Error('resource_conflict');
        task.requested = options.body.enabled; task.ready = task.requested;
        return { data: { ok: true } };
      }
      return { data: catalog };
    }
  });
  vm.runInContext(source, context);
  const power = new context.CameraPower({ onStarted: () => started++, onStopped: () => stopped++, ...control });
  return { power, task, calls, errors, messages, buttons, count: () => ({ started, stopped }) };
}
test('page entry and state reads never start the camera', async () => {
  const f = fixture(); assert.equal(f.calls.length, 0); await f.power.load();
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 0);
  assert.equal(f.buttons.get('camera-start').disabled, false);
});
test('explicit start then stop use only passive camera task and preview callbacks', async () => {
  const f = fixture(); await f.power.change(true); await f.power.change(false);
  const posts = f.calls.filter(row => row.method === 'POST');
  assert.equal(posts.length, 2);
  for (const row of posts) assert.equal(row.path, '/api/logic/feature/s2_camera_preview');
  assert.deepEqual(posts.map(row => row.body.enabled), [true, false]);
  assert.deepEqual(f.count(), { started: 1, stopped: 1 });
  assert.equal(f.errors.length, 0);
});
test('stale, moving, missing and unavailable task observations block start', async () => {
  for (const [patch, options] of [[{}, { stale: true }], [{ can_move: true }, {}], [{ installed: false }, {}], [{ start_available: false }, {}]]) {
    const f = fixture(patch, options); await f.power.change(true);
    assert.equal(f.calls.filter(row => row.method === 'POST').length, 0);
    assert.equal(f.errors.length, 1);
  }
});
test('request rejection never enables browser preview or reports success', async () => {
  const f = fixture({}, { rejected: true }); await f.power.change(true);
  assert.deepEqual(f.count(), { started: 0, stopped: 0 });
  assert.equal(f.errors.length, 1);
});
test('another consumer is shown without stopping its task', async () => {
  const f = fixture({ requested: true, ready: true }, { others: [{ name: 's6_tracker_module', title: 'Tracker', requested: true, resources: ['camera'] }] });
  await f.power.load(); assert.match(f.messages.get('camera-power-state'), /Tracker/);
  await f.power.change(false);
  const posts = f.calls.filter(row => row.method === 'POST');
  assert.equal(posts.length, 1); assert.equal(posts[0].path, '/api/logic/feature/s2_camera_preview');
});

test('single overview toggle reflects confirmed task state and alternates on/off', async () => {
  const f = fixture(); const button = f.buttons.get('camera-toggle');
  assert.equal(button.disabled, true);
  await f.power.load(); assert.equal(button.textContent, 'Kamera: OFF'); assert.equal(button.disabled, false);
  await button.listeners.click();
  assert.equal(button.textContent, 'Kamera: ON'); assert.equal(button['aria-pressed'], 'true');
  await button.listeners.click();
  assert.equal(button.textContent, 'Kamera: OFF'); assert.equal(button['aria-pressed'], 'false');
  assert.deepEqual(f.calls.filter(row => row.method === 'POST').map(row => row.body.enabled), [true, false]);
});
test('unknown state and duplicate clicks cannot issue toggle commands', async () => {
  const f = fixture({}, { stale: true }); await f.power.load(); await f.buttons.get('camera-toggle').listeners.click();
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 0);
  const busy = fixture(); await busy.power.load(); busy.power.busy = true;
  await busy.buttons.get('camera-toggle').listeners.click();
  assert.equal(busy.calls.filter(row => row.method === 'POST').length, 0);
});

test('PROC and OBST buttons share one passive local task and one pending lock', async () => {
  const f = fixture({ name: 's7_obstacle_module' }, { control: { taskName: 's7_obstacle_module',
    options: { provider: 'local' }, toggleIds: ['camera-proc-toggle', 'camera-obst-toggle'], label: '' } });
  await f.power.load();
  await f.buttons.get('camera-proc-toggle').listeners.click();
  for (const id of ['camera-proc-toggle', 'camera-obst-toggle']) assert.equal(f.buttons.get(id).textContent, 'ON');
  await f.buttons.get('camera-obst-toggle').listeners.click();
  for (const id of ['camera-proc-toggle', 'camera-obst-toggle']) assert.equal(f.buttons.get(id).textContent, 'OFF');
  const posts = f.calls.filter(row => row.method === 'POST');
  assert.ok(posts.every(row => row.path === '/api/logic/feature/s7_obstacle_module' && row.body.options.provider === 'local'));
  assert.deepEqual(posts.map(row => row.body.enabled), [true, false]);
});
test('tracker toggle selects only passive tracking and explicit face mode', async () => {
  const f = fixture({ name: 's6_tracker_module' }, { control: { taskName: 's6_tracker_module',
    options: { mode: 'face' }, toggleIds: ['camera-tracker-toggle'] } });
  await f.power.load(); await f.buttons.get('camera-tracker-toggle').listeners.click();
  const post = f.calls.find(row => row.method === 'POST');
  assert.equal(post.path, '/api/logic/feature/s6_tracker_module'); assert.equal(post.body.options.mode, 'face');
  const moving = fixture({ name: 's3_follow_me_face', can_move: true }, { control: { taskName: 's3_follow_me_face' } });
  await moving.power.change(true); assert.equal(moving.calls.filter(row => row.method === 'POST').length, 0);
});

test('processor OFF is not reported as ON because shared camera is running', async () => {
  const f = fixture({name:'s7_obstacle_module'}, {activity:{on:true,service_running:true,data_fresh:true},
    control:{taskName:'s7_obstacle_module',toggleIds:['camera-proc-toggle'],statusIds:['camera-proc-state'],label:''}});
  await f.power.load();
  assert.equal(f.buttons.get('camera-proc-toggle').textContent,'OFF');
  assert.match(f.messages.get('camera-proc-state'),/Przetwarzanie: OFF/);
});

const pipelineFixture = JSON.parse(await readFile(new URL('../config/contracts/camera_pipeline_v1.examples.json',import.meta.url),'utf8')).stopped_status;
test('HTTP LAN with no randomUUID: PROC switches the shared profile and only starts passive S2', async () => {
  const pipeline=structuredClone(pipelineFixture);
  const f=fixture({name:'s7_obstacle_module'}, {pipeline,
    control:{taskName:'s7_obstacle_module',pipelineProcessing:true,toggleIds:['camera-proc-toggle'],statusIds:['camera-proc-state']}});
  await f.power.load();await f.power.change(true);
  assert.equal(f.errors.length,0);
  const posts=f.calls.filter(row=>row.method==='POST');
  assert.deepEqual(posts.map(row=>row.path),['/api/resource/camera/pipeline','/api/resource/camera/pipeline']);
  assert.equal(posts[0].body.action,'configure');assert.equal(posts[0].body.profile.analysis_location,'local');
  assert.equal(posts[1].body.action,'start');
  assert.ok(posts.every(row=>/^[A-Za-z0-9_-]{1,128}$/.test(row.body.request_id)));
});
test('OBST starts its real task after local selection and OFF preserves the shared producer', async () => {
  const pipeline=structuredClone(pipelineFixture);
  const f=fixture({name:'s7_obstacle_module'}, {pipeline,
    control:{taskName:'s7_obstacle_module',toggleIds:['camera-obst-toggle'],statusIds:['camera-obst-state'],options:{provider:'local'}}});
  await f.power.load();await f.power.change(true);await f.power.change(false);
  assert.equal(f.errors.length,0);
  const posts=f.calls.filter(row=>row.method==='POST');
  assert.deepEqual(posts.map(row=>row.path),['/api/resource/camera/pipeline','/api/logic/feature/s7_obstacle_module','/api/logic/feature/s7_obstacle_module']);
  assert.deepEqual(posts.slice(1).map(row=>row.body.enabled),[true,false]);
  assert.ok(posts.every(row=>row.body.action!=='stop'));
});


test('rejected local configuration starts neither shared preview nor OBST task', async () => {
  for (const pipelineProcessing of [true, false]) {
    const pipeline=structuredClone(pipelineFixture);
    const f=fixture({name:'s7_obstacle_module'}, {pipeline,configureRejected:true,
      control:{taskName:'s7_obstacle_module',pipelineProcessing}});
    await f.power.change(true);
    const posts=f.calls.filter(row=>row.method==='POST');
    assert.equal(posts.length,1);
    assert.equal(posts[0].body.action,'configure');
    assert.deepEqual(f.count(),{started:0,stopped:0});
    assert.equal(f.errors[0].message,'camera_pipeline_revision_conflict');
    assert.equal(pipeline.profile.analysis_location,'venom');
  }
});
