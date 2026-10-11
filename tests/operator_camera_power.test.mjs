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
  const calls = [], errors = [], messages = new Map(), buttons = new Map(['camera-start', 'camera-stop'].map(id => [id, { disabled: true, addEventListener() {} }]));
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
