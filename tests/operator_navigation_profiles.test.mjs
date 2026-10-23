import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const sourceUrl = new URL('../web/assets/operator/navigation-profiles.js', import.meta.url);
const raw = (await readFile(sourceUrl, 'utf8')).replace(/^import .*;$/gm, '').replaceAll('export function', 'function').replace('export class', 'class');
const messagesRaw = (await readFile(new URL('../web/assets/operator/navigation-profile-messages.js', import.meta.url), 'utf8')).replaceAll('export ', '');
function fixture({ supported = true, state = 'DISARMED', running = false, failure = null, locale = 'en' } = {}) {
  const calls = [], nodes = {}, shown = [];
  const node = id => nodes[id] ??= { value: '', dataset: {}, disabled: false, textContent: '', children: [], listeners: {},
    addEventListener(type, action) { this.listeners[type] = action; },
    replaceChildren(...children) { this.children = children; this.value = children.find(row => row.selected)?.value || children[0]?.value || ''; } };
  let policy = { revision: 9, behavior: { version: 1, profile_id: 'legacy', profile_revision: 1 } };
  const catalog = () => ({ version: 1, supported, active: policy.behavior, effective_policy_sha256: 'a'.repeat(64),
    profiles: ['legacy', 'cautious', 'balanced', 'fluid'].map(id => ({ id, profile_revision: 1, status: id === 'legacy' ? 'legacy' : 'experimental', parameters: { from_server: 137 } })) });
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
      return { data: structuredClone(path.endsWith('config') ? policy : status) };
    } });
  vm.runInContext(messagesRaw + ';globalThis.t=profileText;', context);
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
  const f = fixture(); assert.deepEqual(f.calls, []);
  await f.panel.load(); await f.panel.refresh();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.match(f.node('navigation-profile-current').textContent, /Previous/);
});
test('missing capability exposes only disabled legacy; unavailable profiles cannot be sent', async () => {
  const f = fixture({ supported: false }); await f.panel.load();
  assert.equal(f.node('navigation-profile').children.length, 1);
  assert.equal(f.node('navigation-profile').disabled, true);
  f.choose('fluid'); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.match(f.node('navigation-profile-message').textContent, /compatible profile catalog/);
});
test('apply submits only server profile revision and policy CAS, without ARM, camera or movement', async () => {
  const f = fixture(); await f.panel.load(); f.choose('fluid'); await f.panel.apply();
  const posts = f.calls.filter(row => row.method === 'POST');
  assert.equal(posts.length, 1); assert.equal(posts[0].path, '/api/navigation/config');
  assert.deepEqual(JSON.parse(JSON.stringify(posts[0].body)), { revision: 9, values: { behavior: { version: 1, profile_id: 'fluid', profile_revision: 1 } } });
  assert.equal(f.policy().mode, 'observe'); assert.equal(f.policy().verified, false);
  assert.equal(f.node('navigation-profile').value, 'fluid');
  assert.match(f.node('navigation-profile-message').textContent, /Profile saved/);
  assert.deepEqual(f.shown, []);
});
test('an edit cannot overwrite a newer revision polled from the other operator panel', async () => {
  const f = fixture(); await f.panel.load(); f.focus(); f.choose('balanced'); f.blur();
  f.changePolicy({ revision: 10 }); await f.panel.load(); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
  assert.equal(f.node('navigation-profile-apply').disabled, true);
  assert.match(f.node('navigation-profile-message').textContent, /Configuration changed in another panel/);
  await f.panel.refresh(); f.choose('cautious'); await f.panel.apply();
  assert.equal(f.calls.find(row => row.method === 'POST').body.revision, 10);
});
test('opening a menu binds its CAS even if another panel changes before selection', async () => {
  const f = fixture(); await f.panel.load(); f.focus();
  f.changePolicy({ revision: 10 }); await f.panel.load(); f.choose('balanced'); f.blur(); await f.panel.apply();
  assert.equal(f.calls.some(row => row.method === 'POST'), false);
});
test('stopped armed pause allows choice while active drive, observation or stale controls block it', async () => {
  const f = fixture({ state: 'ARMED' }); await f.panel.load(); f.choose('balanced');
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
  const f = fixture({ failure: Object.assign(new Error('navigation_config_conflict'), { status: 409 }) });
  await f.panel.load(); f.choose('fluid'); await f.panel.apply();
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 1);
  assert.match(f.node('navigation-profile-message').textContent, /Configuration changed/);
  assert.equal(f.shown.length, 1);
});
test('double apply and an old in-flight read cannot duplicate the mutation', async () => {
  const f = fixture(); await f.panel.load(); f.choose('fluid');
  let release; f.setPostGate(new Promise(resolve => { release = resolve; }));
  const first = f.panel.apply(); await f.panel.apply(); await f.panel.load(); release(); await first;
  assert.equal(f.calls.filter(row => row.method === 'POST').length, 1);
});
test('temporal diagnostics distinguish raw UNKNOWN from SLOW and mark a historical decision', async () => {
  const f = fixture(); f.changeStatus({ running: false, decision: { raw_state: 'UNKNOWN', behavior: { profile_id: 'balanced', profile_revision: 1 },
    temporal: { action: 'slow', state: 'CLEAR', risk: 'warning', reason: 'brief_uncertainty', near_guard_clear: true, evidence_frames: 3, spatial: {} } } });
  await f.panel.load(); const output = f.node('navigation-temporal-state').textContent;
  assert.match(output, /Raw model result: UNKNOWN/); assert.match(output, /warning \/ slow/);
  assert.match(output, /Historical or stale/); assert.match(output, /No confirmed boundary/);
});
test('all new controls have Polish, English and German text', async () => {
  for (const locale of ['pl', 'en', 'de']) {
    const f = fixture({ locale }); await f.panel.load(); f.choose('balanced');
    assert.ok(f.node('navigation-profile-description').textContent.length > 20);
    assert.equal(f.node('navigation-profile-description').textContent.includes('behavior.'), false);
  }
});
