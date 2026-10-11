// No robot connections: task transport and timers are isolated fixtures.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';
const assets = new URL('../web/assets/operator/', import.meta.url);
const model = await import('data:text/javascript;base64,' + Buffer.from(await readFile(new URL('model.js', assets))).toString('base64'));
const source = (await readFile(new URL('camera-power.js', assets), 'utf8')).replace(/^import .*;$/gm, '').replace('export class CameraPower', 'globalThis.CameraPower = class CameraPower');
function fixture(patch = {}, { stale = false, rejected = false, others = [] } = {}) {
  const now = Date.now() / 1000;
  const task = { name: 's2_camera_preview', can_move: false, installed: true, observed_at: now,
    state: 'stopped', requested: false, ready: false, ...patch };
  const catalog = { contract_version: 2, catalog_version: 2, observed_at: stale ? now - 30 : now, features: [task, ...others], units: [] };
  const calls = [], errors = [], messages = new Map(), buttons = new Map(['camera-start', 'camera-stop', 'camera-toggle'].map(id => [id, { disabled: true, listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; }, setAttribute(name, value) { this[name] = value; } }]));
  let started = 0, stopped = 0;
  const context = vm.createContext({ ...model,
    document: { getElementById: id => buttons.get(id) }, window: { addEventListener() {} },
    setInterval: () => 1, clearInterval() {},
    tr: pl => pl, text: (id, value) => messages.set(id, value), showError: error => errors.push(error),
    poll: () => ({ refresh() {}, stop() {} }),
    request: async (path, options = {}) => {
      calls.push({ path, ...options });
      if (options.method === 'POST') {
        if (rejected) throw new Error('resource_conflict');
        task.requested = options.body.enabled; task.ready = task.requested;
        return { data: { ok: true } };
      }
      return { data: catalog };
    }
  });
  vm.runInContext(source, context);
  const power = new context.CameraPower({ onStarted: () => started++, onStopped: () => stopped++ });
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
