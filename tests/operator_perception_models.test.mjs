import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const raw = (await readFile(new URL('../web/assets/operator/perception-models.js', import.meta.url), 'utf8'))
  .replace(/^import .*;$/gm, line => line.replace(/[^\n]/g, ' ')).replace('export class', '       class');
function fixture({ provider = 'venom', hostFails = false, armed = false } = {}) {
  const calls = [], nodes = {}, messages = [];
  const node = id => nodes[id] ??= { value: '', textContent: '', dataset: {}, disabled: false, children: [],
    addEventListener() {}, replaceChildren(...children) { this.children = children; this.value = children.find(row => row.selected)?.value || children[0]?.value || ''; } };
  let pipeline = { contract_id: 'rider.camera_pipeline', contract_version: 1, revision: 4, state: 'stopped',
    profile: { analysis_location: provider, local_engine: 'canny', remote_transport: 'snapshots' },
    capabilities: { analysis_locations: ['local', 'venom'] } };
  const local = { models: [{ id: 'local-canny', label: 'Canny', engine: 'canny', installation: 'ready', selectable: true },
    { id: 'local-ssd', label: 'SSD', engine: 'ssd', installation: 'ready', selectable: true }],
    selected_model_id: 'local-canny', active_model_id: null };
  let host = { models: [{ id: 'segformer-b0-ade20k', label: 'SegFormer', installation: 'ready', selectable: true },
    { id: 'fast-scnn-floor', label: 'Fast SCNN', installation: 'unavailable', selectable: false, reason: 'unqualified' }],
    selection: { model_id: 'segformer-b0-ade20k' }, diagnostics: { runtime: { state: 'ready', active_model_id: 'segformer-b0-ade20k' } } };
  const context = vm.createContext({
    document: { getElementById: node, createElement: () => ({}), activeElement: null },
    window: { addEventListener() {} }, tr: (_pl, en) => en, text: (id, value) => { node(id).textContent = value; },
    showError: error => messages.push(error.message), requestId: () => 'fixture-request',
    validPipeline: value => !!value?.profile, poll: load => ({ refresh: load, stop() {} }),
    request: async (path, options = {}) => {
      calls.push({ path, ...options });
      if (path === '/api/navigation/models' && hostFails) throw new Error('Host offline');
      const data = path === '/api/resource/camera/pipeline' ? pipeline : path === '/api/navigation/local-models' ? local
        : path === '/api/navigation/config' ? { revision: 9, perception: {} } : host;
      return { data: structuredClone(data) };
    },
  });
  const Class = vm.runInContext(raw + ';PerceptionModels', context);
  const panel = new Class({ state: { state: armed ? 'ARMED' : 'DISARMED' } });
  return { panel, calls, nodes, node, local, messages,
    setHost: value => { host = value; }, setPipeline: value => { pipeline = value; } };
}
test('constructor does not install, start camera, arm or move', () => {
  assert.deepEqual(fixture().calls, []);
});
test('Pi forwards only selected id and device config CAS to Venom', async () => {
  const f = fixture(); await f.panel.load();
  await f.panel.applyModel();
  const posts = f.calls.filter(call => call.method === 'POST');
  assert.equal(posts.length, 1); assert.equal(posts[0].path, '/api/navigation/model');
  assert.deepEqual(JSON.parse(JSON.stringify(posts[0].body)), { revision: 9, model_id: 'segformer-b0-ade20k' });
});
test('unavailable host models cannot be chosen', async () => {
  const f = fixture(); await f.panel.load();
  assert.equal(f.node('perception-model').children[1].disabled, true);
  f.node('perception-model').value = 'fast-scnn-floor'; await f.panel.applyModel();
  assert.equal(f.calls.some(call => call.method === 'POST'), false);
});
test('local models remain available with host offline and use existing camera profile', async () => {
  const f = fixture({ provider: 'local', hostFails: true }); await f.panel.load();
  f.node('perception-model').value = 'local-ssd'; await f.panel.applyModel();
  const posts = f.calls.filter(call => call.method === 'POST');
  assert.equal(posts.length, 1); assert.equal(posts[0].path, '/api/resource/camera/pipeline');
  assert.equal(posts[0].body.action, 'configure'); assert.equal(posts[0].body.expected_revision, 4);
  assert.equal(posts[0].body.profile.local_engine, 'ssd');
  assert.equal(posts[0].body.profile.analysis_location, 'local');
  assert.equal(posts[0].body.profile.remote_transport, 'snapshots');
});
test('provider change configures only existing pipeline and never requests start', async () => {
  const f = fixture(); await f.panel.load(); f.node('perception-provider').value = 'local';
  await f.panel.applyProvider();
  const post = f.calls.find(call => call.method === 'POST');
  assert.equal(post.path, '/api/resource/camera/pipeline');
  assert.equal(post.body.profile.analysis_location, 'local');
  assert.equal(post.body.action, 'configure');
});
test('poll updates selected versus loaded model after choice in other panel', async () => {
  const f = fixture(); await f.panel.load();
  f.setHost({ models: [{ id: 'depth-anything-v2-indoor-small', label: 'Depth', installation: 'ready', selectable: true }],
    selection: { model_id: 'depth-anything-v2-indoor-small' }, diagnostics: { runtime: { state: 'loading' } } });
  await f.panel.load();
  assert.equal(f.node('perception-model').value, 'depth-anything-v2-indoor-small');
  assert.match(f.node('perception-selected').textContent, /depth-anything/);
  assert.match(f.node('perception-active').textContent, /no confirmed result/);
});
test('armed operator sees disabled change controls', async () => {
  const f = fixture({ armed: true }); await f.panel.load();
  assert.equal(f.node('perception-provider-apply').disabled, true);
  assert.equal(f.node('perception-model-apply').disabled, true);
});
