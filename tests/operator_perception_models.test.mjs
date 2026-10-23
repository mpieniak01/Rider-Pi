import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const sourceUrl = new URL('../web/assets/operator/perception-models.js', import.meta.url);
const raw = (await readFile(sourceUrl, 'utf8'))
  .replace(/^import .*;$/gm, line => line.replace(/[^\n]/g, ' ')).replace('export class', '       class');
function fixture({ provider = 'venom', hostFails = false, armed = false } = {}) {
  const calls = [], nodes = {}, messages = [];
  const node = id => nodes[id] ??= { value: '', textContent: '', dataset: {}, disabled: false, children: [],
    listeners: {}, addEventListener(type, listener) { this.listeners[type] = listener; }, replaceChildren(...children) { this.children = children; this.value = children.find(row => row.selected)?.value || children[0]?.value || ''; } };
  let pipeline = { contract_id: 'rider.camera_pipeline', contract_version: 1, revision: 4, state: 'stopped',
    profile: { analysis_location: provider, local_engine: 'canny', remote_transport: 'snapshots' },
    capabilities: { analysis_locations: ['local', 'venom'] } };
  const local = { models: [{ id: 'local-canny', label: 'Canny', engine: 'canny', installation: 'ready', selectable: true },
    { id: 'local-ssd', label: 'SSD', engine: 'ssd', installation: 'ready', selectable: true }],
    selected_model_id: 'local-canny', active_model_id: null };
  let host = { models: [{ id: 'segformer-b0-ade20k', label: 'SegFormer', installation: 'ready', selectable: true },
    { id: 'fast-scnn-floor', label: 'Fast SCNN', installation: 'unavailable', selectable: false, reason: 'unqualified' }],
    selection: { model_id: 'segformer-b0-ade20k' }, diagnostics: { runtime: { state: 'active', active_model_id: 'segformer-b0-ade20k' } } };
  let policy = { revision: 9, perception: {} };
  const document = { getElementById: node, createElement: () => ({}), activeElement: null };
  const context = vm.createContext({
    document,
    window: { addEventListener() {} }, tr: (_pl, en) => en, text: (id, value) => { node(id).textContent = value; },
    showError: error => messages.push(error.message), requestId: () => 'fixture-request',
    validPipeline: value => !!value?.profile, poll: load => ({ refresh: load, stop() {} }),
    request: async (path, options = {}) => {
      calls.push({ path, ...options });
      if (path === '/api/navigation/models' && hostFails) throw new Error('Host offline');
      const data = path === '/api/resource/camera/pipeline' ? pipeline : path === '/api/navigation/local-models' ? local
        : path === '/api/navigation/config' ? policy : host;
      return { data: structuredClone(data) };
    },
  });
  const Class = vm.runInContext(raw + ';PerceptionModels', context, { filename: sourceUrl.href });
  const panel = new Class({ state: { state: armed ? 'ARMED' : 'DISARMED' } });
  return { panel, calls, nodes, node, local, messages,
    setHost: value => { host = value; }, setPipeline: value => { pipeline = value; },
    setPolicy: value => { policy = value; }, getPipeline: () => structuredClone(pipeline),
    focus: id => { document.activeElement = node(id); node(id).listeners.focus?.(); },
    change: (id, value) => { node(id).value = value; node(id).listeners.change?.(); },
  };
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


test('host runtime uses canonical active state for the loaded model', async () => {
  const f = fixture(); await f.panel.load();
  assert.match(f.node('perception-active').textContent, /segformer-b0-ade20k/);
  f.setHost({ models: [], diagnostics: { runtime: { state: 'loading', active_model_id: 'segformer-b0-ade20k' } } });
  await f.panel.load();
  assert.match(f.node('perception-active').textContent, /no confirmed result/);
});

test('draft host model keeps its original CAS across an external policy revision', async () => {
  const f = fixture(); await f.panel.load();
  f.focus('perception-model'); f.change('perception-model', 'segformer-b0-ade20k');
  f.setPolicy({ revision: 10, perception: {} }); await f.panel.load();
  assert.equal(f.node('perception-model-apply').disabled, true);
  await f.panel.applyModel();
  assert.equal(f.calls.some(call => call.method === 'POST'), false);
  assert.match(f.node('perception-error').textContent, /Settings changed in another panel/);
  await f.panel.refresh();
  assert.equal(f.node('perception-model-apply').disabled, false);
  f.change('perception-model', 'segformer-b0-ade20k'); await f.panel.applyModel();
  assert.equal(f.calls.find(call => call.method === 'POST').body.revision, 10);
});

test('provider draft cannot overwrite a fresh pipeline read from the other panel', async () => {
  const f = fixture(); await f.panel.load();
  f.focus('perception-provider'); f.change('perception-provider', 'local');
  f.setPipeline({ ...f.getPipeline(), revision: 5 }); await f.panel.load();
  assert.equal(f.node('perception-provider').value, 'local');
  assert.equal(f.node('perception-provider-apply').disabled, true);
  await f.panel.applyProvider();
  assert.equal(f.calls.some(call => call.method === 'POST'), false);
  assert.match(f.node('perception-error').textContent, /Refresh models and choose again/);
});

test('focused unchanged menu still retains its opening revision until refresh', async () => {
  const f = fixture(); await f.panel.load();
  f.focus('perception-model');
  f.setPolicy({ revision: 10, perception: {} }); await f.panel.load();
  f.change('perception-model', 'segformer-b0-ade20k');
  await f.panel.applyModel();
  assert.equal(f.calls.some(call => call.method === 'POST'), false);
});

test('draft local engine never uses a new pipeline CAS obtained after editing began', async () => {
  const f = fixture({ provider: 'local' }); await f.panel.load();
  f.focus('perception-model'); f.change('perception-model', 'local-ssd');
  f.setPipeline({ ...f.getPipeline(), revision: 5 }); await f.panel.load();
  await f.panel.applyModel();
  assert.equal(f.calls.some(call => call.method === 'POST'), false);
  await f.panel.refresh();
  assert.equal(f.node('perception-model').value, 'local-canny');
  f.change('perception-model', 'local-ssd'); await f.panel.applyModel();
  assert.equal(f.calls.find(call => call.method === 'POST').body.expected_revision, 5);
});
