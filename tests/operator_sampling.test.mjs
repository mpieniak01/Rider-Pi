// Isolated fake fetch/timers; no API connection or actuator is available.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
const assets = new URL('../web/assets/operator/', import.meta.url);
const source = (await readFile(new URL('transport.js', assets), 'utf8')).replace(/^import .*;$/gm, '');
async function fixture() {
  let clock = 1000;
  const calls = [], timers = new Map(), listeners = {};
  let responder = async () => ({ ok: true });
  const document = { hidden: false, addEventListener: (event, cb) => { listeners[event] = cb; }, removeEventListener() {} };
  let id = 0;
  const context = vm.createContext({
    Date: { now: () => clock }, document, AbortController,
    setTimeout: (action, delay) => { timers.set(++id, { action, delay }); return id; },
    clearTimeout: timer => timers.delete(timer),
    API_ACCEPT: 'application/vnd.rider.api+json;version=1', responseFamily: () => '',
    setServerClock() {}, errorMessage: (_, fallback) => fallback,
    decodeResponse: data => ({ data, canonical: false, meta: null }),
    fetch: async (path, options) => {
      calls.push({ path, options });
      const data = await responder(path, options);
      return { status: 200, ok: true, json: async () => data };
    }
  });
  const module = new vm.SourceTextModule(source, { context });
  await module.link(() => {}); await module.evaluate();
  return { api: module.namespace, calls, timers, document, listeners,
    clock: value => { clock = value; }, respond: value => { responder = value; } };
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('catalog widgets share flight and recent result without rewriting observation time', async () => {
  const f = await fixture();
  f.respond(async () => ({ observed_at: .5, ok: true }));
  const [one, two] = await Promise.all([f.api.request('/api/logic/catalog'), f.api.request('/api/logic/catalog')]);
  assert.equal(f.calls.length, 1); assert.equal(one, two);
  f.clock(1800);
  assert.equal(await f.api.request('/api/logic/catalog'), one);
  assert.equal(f.calls.length, 1); assert.equal(one.data.observed_at, .5);
  f.clock(2000);
  await f.api.request('/api/logic/catalog');
  assert.equal(f.calls.length, 2);
});

test('safety and settings are always fresh; explicit catalog recheck bypasses cache', async () => {
  const f = await fixture();
  for (const path of ['/api/control/state', '/api/control/settings', '/state']) {
    await f.api.request(path); await f.api.request(path);
  }
  assert.equal(f.calls.length, 6);
  await f.api.request('/api/logic/catalog');
  await f.api.request('/api/logic/catalog', { force: true });
  assert.equal(f.calls.length, 8);
});

test('STOP invalidates catalog before and after mutation with no contract negotiation', async () => {
  const f = await fixture();
  await f.api.request('/api/logic/catalog');
  await f.api.request('/api/control', { method: 'POST', body: { action: 'stop' } });
  await f.api.request('/api/logic/catalog');
  assert.deepEqual(f.calls.map(row => row.path), ['/api/logic/catalog', '/api/control', '/api/logic/catalog']);
});

test('a read started before mutation cannot refill the post-mutation cache', async () => {
  const f = await fixture(); let finish;
  f.respond(path => path === '/api/logic/catalog' ? new Promise(resolve => { finish = resolve; }) : { ok: true });
  const pending = f.api.request('/api/logic/catalog');
  await f.api.request('/api/control', { method: 'POST', body: { action: 'stop' } });
  finish({ ok: true, old: true }); await pending;
  f.respond(async () => ({ ok: true, old: false }));
  const fresh = await f.api.request('/api/logic/catalog');
  assert.equal(fresh.data.old, false); assert.equal(f.calls.length, 3);
});

test('profile beats group identical reads and spread services/system work', async () => {
  const f = await fixture();
  const a = f.api.poll(async () => {}, { profile: 'services' });
  const b = f.api.poll(async () => {}, { profile: 'system' });
  await flush();
  assert.deepEqual([...f.timers.values()].map(timer => timer.delay).sort((x, y) => x - y), [1500, 4250]);
  a.stop(); b.stop(); assert.equal(f.timers.size, 0);
});

test('server timing hints affect presentation only; hidden pages sleep', async () => {
  const f = await fixture();
  f.respond(async () => ({ sampling: { panel_intervals_ms: { system: 1500, services: 50000, telemetry: 1 } } }));
  await f.api.request('/sysinfo');
  let calls = 0;
  const poller = f.api.poll(async () => { calls++; }, { profile: 'system' });
  await flush();
  assert.equal([...f.timers.values()][0].delay, 1000);
  f.document.hidden = true; f.listeners.visibilitychange(); await poller.refresh();
  assert.equal(calls, 1); assert.equal(f.timers.size, 0);
  f.document.hidden = false; f.listeners.visibilitychange(); await flush();
  assert.equal(calls, 2); poller.stop();
});

test('history uses real timestamps, preserves peaks and leaves gaps after inactivity', async () => {
  const src = (await readFile(new URL('overview.js', assets), 'utf8'))
    .replace(/^import .*;$/gm, '').replace('export class Overview', 'globalThis.Overview = class Overview');
  const context = vm.createContext({});
  vm.runInContext(src, context);
  const paths = []; let current;
  const ctx = { beginPath() { current = []; paths.push(current); }, moveTo(x, y) { current.push(['move', x, y]); },
    lineTo(x, y) { current.push(['line', x, y]); }, stroke() {} };
  context.Overview.prototype.drawHistory.call({ axes: () => ({ ctx, x: 0, y: 0, width: 60, height: 100 }) },
    [10, 20, 30], [40, 40, 40], [80, 90, 95], [1000, 1001, 1030]);
  assert.ok(Math.abs(paths[0][0][2] - 20) < 1e-9); // Peak 80%, not the one-second average.
  assert.deepEqual(Array.from(paths[1], point => point[0]), ['move', 'line', 'move']);
  assert.equal(paths[1][0][1], 30);
  assert.equal(paths[1][2][1], 60);
});

test('overview reads idle metadata once, skips absent detector and resumes after ON', async () => {
  const src = (await readFile(new URL('overview.js', assets), 'utf8'))
    .replace(/^import .*;$/gm, '').replace('export class Overview', 'globalThis.Overview = class Overview');
  const calls = [];
  const context = vm.createContext({ request: async path => { calls.push(path); return { data: {} }; } });
  vm.runInContext(src, context);
  const view = { state: { camera: { activity: { on: false } } }, visionIdleLoaded: false, renderVision() {} };
  const load = () => context.Overview.prototype.loadVision.call(view);
  await load(); await load();
  assert.deepEqual(calls, ['/vision/snap-info?light=1']);
  view.state.camera.activity.on = true;
  await load();
  assert.deepEqual(calls.slice(-2), ['/vision/snap-info?light=1', '/vision/obstacle']);
  view.state.camera.activity.on = false;
  await load(); const count = calls.length; await load();
  assert.equal(calls.length, count); assert.equal(view.obstacle, null);
});

test('a missing timestamp breaks timed history instead of falling back to index',async()=>{
  const src=(await readFile(new URL('overview.js',assets),'utf8'))
    .replace(/^import .*;$/gm,'').replace('export class Overview','globalThis.Overview = class Overview');
  const context=vm.createContext({});vm.runInContext(src,context);
  const marks=[];
  const ctx={beginPath(){},moveTo(x,y){marks.push('move');},lineTo(x,y){marks.push('line');},stroke(){}};
  context.Overview.prototype.drawHistory.call({axes:()=>({ctx,x:0,y:0,width:60,height:100})},
    [10,20,30],[],[],[1000,null,1006]);
  assert.deepEqual(marks,['move','move']);
});
