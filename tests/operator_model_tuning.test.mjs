import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const sourceUrl = new URL('../web/assets/operator/model-tuning.js', import.meta.url);
const messagesUrl = new URL('../web/assets/operator/navigation-profile-messages.js', import.meta.url);
const raw = (await readFile(sourceUrl, 'utf8'))
  .replace(/^import .*;$/gm, line => line.replace(/[^\n]/g, ' ')).replaceAll('export ', '       ');
const messages = await readFile(messagesUrl, 'utf8');
const translations = JSON.parse(await readFile(new URL('../web/assets/operator/navigation-profile-messages.json', import.meta.url), 'utf8'));
const seg = 'segformer-b0-ade20k', yolo = 'yolo26n-sem-ade20k';
async function fixture({ supported = true, provider = 'venom', locale = 'en' } = {}) {
  const calls = [], nodes = {}, shown = [];
  const node = id => nodes[id] ??= { value: '', textContent: '', hidden: false, disabled: false, placeholder: '',
    options: id.endsWith('surface') ? [{ value: 'floor_only' }, { value: 'floor_rug' }] : [{ value: 'inherit' }, { value: 'custom' }],
    listeners: {}, addEventListener(type, action) { this.listeners[type] = action; }, setAttribute() {} };
  let policy = { revision: 7, model_tuning_supported: supported, perception: { engine: 'segformer', model_id: seg, artifact_sha256: 'a'.repeat(64),
    residual_limit: .06, outlier_limit: .005, slope_min: 2, semantic_models: {
      [yolo]: { version: 1, surface: 'floor_rug', pixel_confidence: .9 },
    } }, perception_tuning: { version: 1, active_model_id: seg, effective: {
      pixel_confidence: .8, min_floor_fraction: 1, max_uncertain_fraction: .01, min_region_fraction: 0,
    } } };
  let status = { running: false, mode: 'observe' }, pipeline = { revision: 4, profile: { analysis_location: provider, local_engine: 'canny' } };
  let fresh = true, failure = null;
  const safety = { state: { state: 'DISARMED', generation: 'one', moving: false, operator_control: { state: 'paused' } }, clockFresh: () => fresh };
  const document = { documentElement: { lang: locale }, getElementById: node, activeElement: null };
  const context = vm.createContext({ document, structuredClone, window: { addEventListener() {} },
    text: (id, value) => { node(id).textContent = value; }, showError: error => shown.push(error.message),
    poll: load => ({ refresh: load, stop() {} }), request: async (path, options = {}) => {
      calls.push({ path, ...options });
      if (options.method === 'POST') {
        if (failure) throw failure;
        assert.equal(path, '/api/navigation/config'); assert.equal(options.body.revision, policy.revision);
        policy = { ...policy, revision: policy.revision + 1, mode: 'observe', verified: false,
          perception: structuredClone(options.body.values.perception) };
        return { data: { config: structuredClone(policy) } };
      }
      return { data: structuredClone(path.endsWith('/config') ? policy : path.endsWith('/pipeline') ? pipeline : status) };
    } });
  const messageModule = new vm.SourceTextModule(messages, { context, identifier: messagesUrl.href, initializeImportMeta(meta) { meta.url = messagesUrl.href; } });
  context.URL = URL; context.AbortController = AbortController; context.setTimeout = setTimeout; context.clearTimeout = clearTimeout;
  context.fetch = async () => ({ ok: true, json: async () => structuredClone(translations) });
  await messageModule.link(() => assert.fail('Unexpected import')); await messageModule.evaluate();
  context.t = messageModule.namespace.profileText;
  const Class = vm.runInContext(raw + ';ModelTuning', context, { filename: sourceUrl.href }), panel = new Class(safety);
  return { panel, calls, node, shown, safety, helpers: { tuningModelId: vm.runInContext("tuningModelId", context) }, policy: () => structuredClone(policy),
    change(id, value, event = 'change') { document.activeElement = node(id); node(id).listeners.focus?.(); node(id).value = value; node(id).listeners[event]?.(); document.activeElement = null; },
    setPolicy(patch) { policy = { ...policy, ...patch }; }, setStatus(patch) { status = { ...status, ...patch }; },
    setPipeline(patch) { pipeline = { ...pipeline, ...patch }; }, setFresh(value) { fresh = value; }, setFailure(error) { failure = error; },
  };
}
test('construction and repeated reads do not install, arm, start camera or write configuration', async () => {
  const f = await fixture(); assert.equal(f.calls.length, 0); await f.panel.load(); await f.panel.refresh();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.equal(f.node('model-tuning-surface').value, 'floor_only');
  assert.equal(f.node('model-tuning-mode-pixel_confidence').value, 'inherit');
  assert.equal(f.node('model-tuning-pixel_confidence').placeholder, '0.8');
});
test('surface mapping and a nullable/custom threshold save only perception with original CAS, preserving the other model', async () => {
  const f = await fixture(); await f.panel.load(); f.change('model-tuning-surface', 'floor_rug');
  f.change('model-tuning-mode-pixel_confidence', 'custom'); f.change('model-tuning-pixel_confidence', '.82', 'input'); await f.panel.apply();
  const posts = f.calls.filter(row => row.method === 'POST'); assert.equal(posts.length, 1);
  const body = posts[0].body; assert.equal(body.revision, 7); assert.deepEqual(Object.keys(body.values), ['perception']);
  assert.equal(body.values.perception.semantic_models[seg].surface, 'floor_rug');
  assert.equal(body.values.perception.semantic_models[seg].pixel_confidence, .82);
  assert.equal(body.values.perception.semantic_models[yolo].pixel_confidence, .9);
  assert.equal(body.values.perception.model_id, seg); assert.equal(body.values.perception.artifact_sha256, 'a'.repeat(64));
  assert.equal(f.policy().mode, 'observe'); assert.equal(f.policy().verified, false);
});
test('custom bounds and empty numeric inputs cannot be persisted; inheritance remains nullable', async () => {
  const f = await fixture(); await f.panel.load(); f.change('model-tuning-mode-min_region_fraction', 'custom');
  f.change('model-tuning-min_region_fraction', '.03', 'input'); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.match(f.node('model-tuning-message').textContent, /Enter numbers within the shown ranges/);
  f.change('model-tuning-min_region_fraction', '', 'input'); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  f.change('model-tuning-mode-min_region_fraction', 'inherit'); f.change('model-tuning-surface', 'floor_rug'); await f.panel.apply();
  assert.equal(f.policy().perception.semantic_models[seg].min_region_fraction, null);
});
test('external revision, selected model, generation and pipeline changes invalidate a pending draft', async () => {
  for (const change of [
    f => f.setPolicy({ revision: 8 }),
    f => f.setPolicy({ revision: 8, perception: { ...f.policy().perception, model_id: yolo } }),
    f => { f.safety.state.generation = 'two'; },
    f => f.setPipeline({ revision: 5 }),
  ]) {
    const f = await fixture(); await f.panel.load(); f.change('model-tuning-surface', 'floor_rug'); change(f); await f.panel.load(); await f.panel.apply();
    assert.equal(f.calls.some(row => row.method === 'POST'), false);
    assert.match(f.node('model-tuning-message').textContent, /Configuration changed/);
  }
});
test('active driving, observation, stale state and stale clock all block applying a model change', async () => {
  for (const change of [
    f => { f.safety.state.moving = true; }, f => f.setStatus({ running: true, mode: 'drive' }),
    f => f.setStatus({ running: true }), f => { f.safety.state.stale = true; }, f => f.setFresh(false),
  ]) {
    const f = await fixture(); await f.panel.load(); f.change('model-tuning-surface', 'floor_rug'); change(f); await f.panel.load(); await f.panel.apply();
    assert.equal(f.calls.some(row => row.method === 'POST'), false); assert.equal(f.node('model-tuning-apply').disabled, true);
  }
});
test('older backend explains updates and disables all semantic controls', async () => {
  const f = await fixture({ supported: false }); await f.panel.load();
  assert.equal(f.node('model-tuning-surface').disabled, true); assert.match(f.node('model-tuning-message').textContent, /Update both sides/);
  f.change('model-tuning-surface', 'floor_rug'); await f.panel.apply(); assert.equal(f.calls.some(row => row.method === 'POST'), false);
});
test('local provider hides host model fields and explains the selected Pi algorithm without changing it', async () => {
  const f = await fixture({ provider: 'local' }); await f.panel.load();
  assert.equal(f.node('model-tuning-semantic').hidden, true); assert.equal(f.node('model-tuning-depth').hidden, true);
  assert.match(f.node('model-tuning-message').textContent, /canny/);
  assert.match(f.node('model-tuning-current').textContent, /Rider-Pi · canny/);
  f.change('model-tuning-surface', 'floor_rug'); await f.panel.apply(); assert.equal(f.calls.some(row => row.method === 'POST'), false);
});
test('depth model exposes geometry only and retains semantic overrides for subsequent model switching', async () => {
  const f = await fixture(); const p = f.policy(); f.setPolicy({ perception: { ...p.perception, engine: 'depth_plane', model_id: 'depth-anything-v2-indoor-small' } });
  await f.panel.load(); assert.equal(f.node('model-tuning-depth').hidden, false); assert.equal(f.node('model-tuning-semantic').hidden, true);
  f.change('model-tuning-outlier_limit', '.8', 'input'); await f.panel.apply();
  assert.equal(f.policy().perception.outlier_limit, .008); assert.equal(f.policy().perception.semantic_models[yolo].pixel_confidence, .9);
});
test('server conflict is visible and is never retried automatically', async () => {
  const f = await fixture(); await f.panel.load(); f.change('model-tuning-surface', 'floor_rug'); f.setFailure(new Error('navigation_config_conflict')); await f.panel.apply();
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 1); assert.match(f.node('model-tuning-message').textContent, /Configuration changed/);
});
test('new model controls have complete Polish, English and German text', async () => {
  for (const locale of ['pl', 'en', 'de']) {
    const f = await fixture({ locale }); await f.panel.load();
    assert.ok(f.node('model-tuning-title').textContent.length > 10); assert.equal(f.node('model-tuning-title').textContent.includes('tuning.'), false);
    assert.ok(f.node('model-tuning-label-max_uncertain_fraction').textContent.length > 10);
  }
});

test('legacy SegFormer resolves effective settings and floor/rug writes without granting identity or weakening CAS', async () => {
  const f = await fixture(); const p = f.policy();
  f.setPolicy({ perception: { ...p.perception, engine: 'segformer', model_id: '' } });
  await f.panel.load();
  assert.equal(f.helpers.tuningModelId(f.policy()), seg); assert.equal(f.panel.effective().pixel_confidence, .8);
  assert.equal(f.node('model-tuning-pixel_confidence').placeholder, '0.8');
  f.change('model-tuning-surface', 'floor_rug'); await f.panel.apply();
  const posts = f.calls.filter(row => row.method === 'POST'); assert.equal(posts.length, 1);
  assert.equal(posts[0].body.revision, 7); assert.equal(posts[0].body.values.perception.model_id, '');
  assert.equal(posts[0].body.values.perception.semantic_models[seg].surface, 'floor_rug');
  f.change('model-tuning-surface', 'floor_only'); f.setPolicy({ revision: 9 }); await f.panel.load(); await f.panel.apply();
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 1);
  for (const input of [null, { perception: {} }, { perception: { engine: 'unknown', model_id: '' } }]) assert.equal(f.helpers.tuningModelId(input), '');
  f.setPolicy({ perception_tuning: { version: 1, active_model_id: yolo, effective: { pixel_confidence: .9 } } });
  await f.panel.load(); assert.equal(f.panel.effective(), null);
});


test('server rejects tuning with a specific operator recovery hint without retry', async () => {
  for (const [code, message] of [
    ['navigation_stop_loops_first', /observation loop/i],
    ['navigation_profile_requires_stopped', /movement/i],
    ['storage_unavailable', /not saved/i],
  ]) {
    const f = await fixture(); await f.panel.load(); f.change('model-tuning-surface', 'floor_rug');
    f.setFailure(Object.assign(new Error('server failed'), { data: { error: { code } } }));
    await f.panel.apply();
    assert.equal(f.calls.filter(row => row.method === 'POST').length, 1);
    assert.equal(f.panel.busy, false);
    assert.ok(f.panel.draft, 'Rejected edits remain available for correction');
    assert.match(f.node('model-tuning-message').textContent, message);
  }
});

test('unknown provider, unavailable safety and a busy mutation never submit settings', async () => {
  const f = await fixture({ provider: 'unknown' }); await f.panel.load();
  assert.equal(f.panel.blocked(), 'tuning.providerUnknown');
  f.setPipeline({ profile: { analysis_location: 'venom' } }); await f.panel.load();
  f.safety.state = null; assert.equal(f.panel.blocked(), 'behavior.block.stale');
  f.safety.state = { state: 'DISARMED', moving: false };
  f.panel.busy = true; assert.equal(f.panel.blocked(), 'behavior.block.busy');
  await f.panel.refresh(); await f.panel.load();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
});

test('unchanged or missing draft does not write while refresh explicitly discards an edit', async () => {
  const f = await fixture(); await f.panel.load(); await f.panel.apply();
  f.change('model-tuning-surface', 'floor_rug');
  assert.ok(f.panel.draft); await f.panel.refresh(); assert.equal(f.panel.draft, null);
  assert.equal(f.node('model-tuning-surface').value, 'floor_only');
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
});
