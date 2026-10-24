import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const sourceUrl = new URL('../web/assets/operator/navigation-profiles.js', import.meta.url);
const raw = (await readFile(sourceUrl, 'utf8')).replace(/^import .*;$/gm, '').replaceAll('export function', 'function').replace('export class', 'class');
const messagesUrl = new URL('../web/assets/operator/navigation-profile-messages.js', import.meta.url);
const messagesRaw = await readFile(messagesUrl, 'utf8');
const translations = JSON.parse(await readFile(new URL('../web/assets/operator/navigation-profile-messages.json', import.meta.url), 'utf8'));
async function fixture({ supported = true, state = 'DISARMED', running = false, failure = null, locale = 'en', provider = 'venom', revisions2 = false } = {}) {
  const calls = [], nodes = {}, shown = [];
  const node = id => nodes[id] ??= { value: '', dataset: {}, disabled: false, textContent: '', children: [], listeners: {},
    addEventListener(type, action) { this.listeners[type] = action; },
    replaceChildren(...children) { this.children = children; this.value = children.find(row => row.selected)?.value || children[0]?.value || ''; } };
  let policy = { revision: 9, behavior: { version: 1, profile_id: 'legacy', profile_revision: 1 } };
  const catalog = () => ({ ...(revisions2 ? { parameter_editing_version: 1, active_parameters: { from_server: 137, ...policy.behavior.overrides } } : {}), version: 1, supported, active: policy.behavior, effective_policy_sha256: 'a'.repeat(64),
    profiles: ['legacy', 'cautious', 'balanced', 'fluid'].map(id => ({ id, profile_revision: revisions2 && id !== 'legacy' ? 2 : 1, status: id === 'legacy' ? 'legacy' : 'experimental', parameters: { from_server: 137 } })) });
  policy.behavior_catalog = catalog();
  let status = { running, mode: running ? 'observe' : 'idle', stale: false };
  let fresh = true, postGate = null;
  const safety = { state: { state, moving: false, operator_control: { state: 'paused' } }, clockFresh: () => fresh };
  const document = { documentElement: { lang: locale }, getElementById: node, createElement: () => ({}), activeElement: null };
  const context = vm.createContext({ document, window: { addEventListener() {} }, text: (id, value) => { node(id).textContent = value; },
    showError: error => shown.push(error.message),
    poll: load => ({ refresh: load, stop() {} }),
    request: async (path, options = {}) => {
      calls.push({ path, ...options });
      if (options.method === 'POST') {
        if (postGate) await postGate;
        if (failure) throw failure;
        assert.equal(options.body.revision, policy.revision);
        policy = { ...policy, revision: policy.revision + 1, mode: 'observe', verified: false, behavior: structuredClone(options.body.values.behavior) };
        policy.behavior_catalog = catalog(); return { data: {ok: true, persisted: true, config: structuredClone(policy)} };
      }
      return { data: structuredClone(path.endsWith('config') ? policy : path.endsWith('pipeline') ? { revision: 4, profile: { analysis_location: provider, local_engine: 'canny' } } : status) };
    } });
  const messageModule = new vm.SourceTextModule(messagesRaw, { context, identifier: messagesUrl.href, initializeImportMeta(meta) { meta.url = messagesUrl.href; } });
  context.URL = URL; context.AbortController = AbortController; context.setTimeout = setTimeout; context.clearTimeout = clearTimeout;
  context.fetch = async () => ({ ok: true, json: async () => structuredClone(translations) });
  await messageModule.link(() => assert.fail('Unexpected import')); await messageModule.evaluate();
  context.t = messageModule.namespace.profileText;
  const Class = vm.runInContext(raw + ';NavigationProfiles', context, { filename: sourceUrl.href });
  const panel = new Class(safety);
  return { panel, calls, nodes, node, shown, safety,
    policy: () => structuredClone(policy),
    changePolicy(patch) { policy = { ...policy, ...patch }; policy.behavior_catalog = catalog(); },
    changeStatus(patch) { status = { ...status, ...patch }; },
    setFresh(value) { fresh = value; }, setPostGate(value) { postGate = value; },
    focus() { document.activeElement = node('navigation-profile'); node('navigation-profile').listeners.focus(); },
    blur() { document.activeElement = null; node('navigation-profile').listeners.blur(); },
    choose(value) { node('navigation-profile').value = value; node('navigation-profile').listeners.change(); },
  };
}
test('new profile widget makes no mutation on construction, loading or refresh', async () => {
  const f = await fixture(); assert.deepEqual(f.calls, []);
  await f.panel.load(); await f.panel.refresh();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.match(f.node('navigation-profile-current').textContent, /Previous/);
});
test('missing capability explains all disabled choices without granting an unavailable profile', async () => {
  const f = await fixture({ supported: false }); await f.panel.load();
  assert.equal(f.node('navigation-profile').children.length, 4);
  assert.equal(f.node('navigation-profile').disabled, true);
  f.choose('fluid'); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.match(f.node('navigation-profile-message').textContent, /Compatible Venom and Rider-Pi updates/);
});
test('apply submits only server profile revision and policy CAS, without ARM, camera or movement', async () => {
  const f = await fixture(); await f.panel.load(); f.choose('fluid'); await f.panel.apply();
  const posts = f.calls.filter(row => row.method === 'POST');
  assert.equal(posts.length, 1); assert.equal(posts[0].path, '/api/navigation/config');
  assert.deepEqual(JSON.parse(JSON.stringify(posts[0].body)), { revision: 9, values: { behavior: { version: 1, profile_id: 'fluid', profile_revision: 1 } } });
  assert.equal(f.policy().mode, 'observe'); assert.equal(f.policy().verified, false);
  assert.equal(f.node('navigation-profile').value, 'fluid');
  assert.match(f.node('navigation-profile-message').textContent, /Settings saved/);
  assert.deepEqual(f.shown, []);
});
test('an edit cannot overwrite a newer revision polled from the other operator panel', async () => {
  const f = await fixture(); await f.panel.load(); f.focus(); f.choose('balanced'); f.blur();
  f.changePolicy({ revision: 10 }); await f.panel.load(); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.equal(f.node('navigation-profile-apply').disabled, true);
  assert.match(f.node('navigation-profile-message').textContent, /Configuration changed in another panel/);
  await f.panel.refresh(); f.choose('cautious'); await f.panel.apply();
  assert.equal(f.calls.find(row => row.method === 'POST').body.revision, 10);
});
test('opening a menu binds its CAS even if another panel changes before selection', async () => {
  const f = await fixture(); await f.panel.load(); f.focus();
  f.changePolicy({ revision: 10 }); await f.panel.load(); f.choose('balanced'); f.blur(); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
});
test('stopped armed pause allows choice while active drive, observation or stale controls block it', async () => {
  const f = await fixture({ state: 'ARMED' }); await f.panel.load(); f.choose('balanced');
  assert.equal(f.node('navigation-profile-apply').disabled, false);
  f.safety.state.moving = true; await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  f.safety.state.moving = false; f.panel.error = '';
  f.changeStatus({ running: true, mode: 'observe' }); await f.panel.load();
  assert.match(f.node('navigation-profile-message').textContent, /End the observation loop/);
  f.changeStatus({ running: false }); await f.panel.load(); f.setFresh(false); f.panel.render();
  assert.equal(f.node('navigation-profile-apply').disabled, true);
});
test('server conflict is displayed once without retry or automatic service changes', async () => {
  const f = await fixture({ failure: Object.assign(new Error('navigation_config_conflict'), { status: 409 }) });
  await f.panel.load(); f.choose('fluid'); await f.panel.apply();
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 1);
  assert.match(f.node('navigation-profile-message').textContent, /Configuration changed/);
  assert.equal(f.shown.length, 1);
});
test('double apply and an old in-flight read cannot duplicate the mutation', async () => {
  const f = await fixture(); await f.panel.load(); f.choose('fluid');
  let release; f.setPostGate(new Promise(resolve => { release = resolve; }));
  const first = f.panel.apply(); await f.panel.apply(); await f.panel.load(); release(); await first;
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 1);
});
test('temporal diagnostics distinguish raw UNKNOWN from SLOW and mark a historical decision', async () => {
  const f = await fixture(); f.changeStatus({ running: false, decision: { raw_state: 'UNKNOWN', behavior: { profile_id: 'balanced', profile_revision: 1 },
    temporal: { action: 'slow', state: 'CLEAR', risk: 'warning', reason: 'brief_uncertainty', near_guard_clear: true, evidence_frames: 3, spatial: {} } } });
  await f.panel.load(); const output = f.node('navigation-temporal-state').textContent;
  assert.match(output, /Raw model result: UNKNOWN/); assert.match(output, /warning \/ slow/);
  assert.match(output, /Historical or stale/); assert.match(output, /No confirmed boundary/);
});
test('all new controls have Polish, English and German text', async () => {
  for (const locale of ['pl', 'en', 'de']) {
    const f = await fixture({ locale }); await f.panel.load(); f.choose('balanced');
    assert.ok(f.node('navigation-profile-description').textContent.length > 20);
    assert.equal(f.node('navigation-profile-description').textContent.includes('behavior.'), false);
  }
});

test('local Pi algorithms block host temporal profiles while retaining a supported Legacy rollback', async () => {
  const f = await fixture({ provider: 'local' }); await f.panel.load(); f.choose('fluid'); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.equal(f.node('navigation-profile-apply').disabled, true);
  assert.match(f.node('navigation-profile-message').textContent, /local Rider-Pi algorithm: canny/);
  f.changePolicy({ behavior: { version: 1, profile_id: 'fluid', profile_revision: 1 } });
  await f.panel.refresh(); f.choose('legacy'); await f.panel.apply();
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 1);
  assert.equal(f.policy().behavior.profile_id, 'legacy');
});


test('temporal diagnostics distinguish current confirmed boundary and unknown near guard', async () => {
  const f = await fixture(); f.changeStatus({ running: true, decision: { raw_state: 'obstacle',
    temporal: { action: 'stop', state: 'obstacle', risk: 'stop', reason: 'unmapped_reason', evidence_frames: 4,
      spatial: { boundary: [[1,2], [3,4]] } } } });
  await f.panel.load(); const text = f.node('navigation-temporal-state').textContent;
  assert.match(text, /unmapped_reason/); assert.match(text, /2/);
  assert.doesNotMatch(text, /Historical or stale/);
  assert.match(text, /unknown/i);
});

test('server stop-loop and stopped-only failures retain draft and clear pending state', async () => {
  for (const code of ['navigation_stop_goals_first', 'navigation_profile_requires_stopped', 'persistence_failed']) {
    const f = await fixture({ failure: Object.assign(new Error(code), { data: { error: { code } } }) });
    await f.panel.load(); f.choose('fluid'); await f.panel.apply();
    assert.equal(f.calls.filter(row => row.method === 'POST').length, 1);
    assert.ok(f.panel.draft); assert.equal(f.panel.busy, false);
    assert.equal(f.shown.length, 1); assert.equal(f.policy().behavior.profile_id, 'legacy');
  }
});


test('v2 catalog preserves an old active revision and submits explicit upgrade', async () => {
  const f = await fixture({ revisions2: true });
  f.changePolicy({ behavior: {version:1, profile_id:'fluid', profile_revision:1} });
  await f.panel.load();
  assert.equal(f.node('navigation-profile').disabled, false);
  assert.equal(f.policy().behavior.profile_revision, 1);
  f.choose('fluid'); await f.panel.apply();
  assert.equal(f.policy().behavior.profile_revision, 2);
});
test('saved custom correction stays visible and can be reset to named preset', async () => {
  const f = await fixture({ revisions2: true });
  f.changePolicy({ behavior: {version:1, profile_id:'fluid', profile_revision:2,overrides:{obstacle_support_frames:3}} });
  await f.panel.load();
  assert.match(f.node('navigation-profile-current').textContent, /Custom settings/);
  assert.match(f.node('navigation-profile-parameters').textContent, /obstacle_support_frames/);
  f.choose('fluid'); await f.panel.apply();
  assert.equal(f.policy().behavior.overrides, undefined);
  assert.doesNotMatch(f.node('navigation-profile-current').textContent, /Custom settings/);
});
