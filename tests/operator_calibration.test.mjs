// Pure contracts and in-memory DOM/REST only. No socket, BUS, SDK or robot exists.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const model = await import('data:text/javascript;base64,' + Buffer.from(await readFile(
  path.join(root, 'web/assets/operator/calibration-model.js'))).toString('base64'));
const now = 1000, digest = 'a'.repeat(64), generation = 'fixture-generation';
const safe = () => ({ contract_version: 1, state: 'DISARMED', generation, observed_at: now,
  ready: true, hardware_ready: true, last_seq: 4 });
const runtime = () => ({ schema_version: 1, actuation: false, stale: false, error: null, status: 'unconfigured',
  motion: { observed_at: now, generation, moving: false, target: { lx: 0, az: 0 }, output: { lx: 0, az: 0 }, instance_id: 'motion-fixture' },
  odometry: { observed_at: now, contract_version: 1, actuation: false, instance_id: 'odometry-fixture' } });
function applied() {
  const row = runtime();
  row.status = 'applied'; row.confirmation = 'executed'; row.model_ready = false;
  row.active = { profile_digest: digest, activated_at: 990, request_id: 'activation-fixture', command_generation: generation, seq: 5 };
  row.motion.calibration = { observed_at: now, profile_digest: digest, source: 'profile', instance_id: 'motion-fixture',
    activation_request_id: 'activation-fixture', command_generation: generation, applied_generation: 'new-generation', odometry_error: 'manual_calibration_required',
    applied_ack: { observed_at: 991, action: 'activate_calibration', accepted: true, actuation: false, source: 'manual',
      profile_digest: digest, request_id: 'activation-fixture', command_generation: generation, seq: 5,
      instance_id: 'motion-fixture', status: 'executed', generation: 'new-generation' } };
  row.odometry.calibration = { observed_at: now, profile_digest: digest, source: 'profile', motion_instance_id: 'motion-fixture',
    activation_request_id: 'activation-fixture', command_generation: generation, applied_generation: 'new-generation', seq: 5, model_ready: false };
  return row;
}
test('draft default has full observations/conditions and no verified or physical measurements', () => {
  const profile = model.defaultProfile(); profile.name = 'fixture';
  assert.equal(model.profileError(profile), null);
  assert.equal(profile.provenance.kind, 'draft'); assert.equal(profile.odometry.manual_verified, false);
  assert.equal(Object.keys(profile.odometry.observations).length, 10);
  assert.equal(profile.odometry.conditions.power_cable, ''); assert.equal(profile.odometry.conditions.commit, '');
  assert.deepEqual(profile.odometry.linear_m_s, {}); assert.deepEqual(profile.measurements, []);
});
test('imports are bounded UTF8, historical and unverified even with a claimed manual record', () => {
  const profile = model.defaultProfile(); profile.name = 'imported'; profile.provenance.kind = 'manual';
  profile.odometry.manual_verified = true;
  const value = model.parseImportedProfile(JSON.stringify({ digest, profile }));
  assert.equal(value.provenance.kind, 'historical'); assert.equal(value.odometry.manual_verified, false);
  assert.equal(profile.odometry.manual_verified, true);
  assert.throws(() => model.parseImportedProfile(' '.repeat(model.MAX_PROFILE_BYTES + 1)));
  assert.throws(() => model.parseImportedProfile(JSON.stringify({ ...profile, name: 'ę'.repeat(40000) })));
});
test('signed measured tables enforce reachable SDK steps without inferring panel speed', () => {
  assert.deepEqual(model.measuredTable([{ step: -1, rate: -.2 }, { step: 1, rate: .3 }], 12), { '-1': -.2, '1': .3 });
  assert.deepEqual(model.measuredTable([{ step: -20, rate: -.4 }, { step: 70, rate: .9 }], 70), { '-20': -.4, '70': .9 });
  for (const rows of [[{ step: 0, rate: 0 }], [{ step: 1, rate: -.2 }], [{ step: 1, rate: Infinity }],
    [{ step: '', rate: .2 }], [{ step: 1, rate: .2 }, { step: 1, rate: .3 }]]) assert.throws(() => model.measuredTable(rows, 12));
  for (const step of [1, 19, -19, 71]) assert.throws(() => model.measuredTable([{ step, rate: step / 100 }], 70));
});
test('manual verification requires matching raw evidence and all actual conditions', () => {
  const profile = model.defaultProfile(); profile.name = 'manual'; profile.provenance = { kind: 'manual', notes: 'fixture evidence' };
  Object.keys(profile.odometry.conditions).forEach(key => { profile.odometry.conditions[key] = 'fixture'; });
  Object.assign(profile.odometry, { manual_verified: true, measurement_id: 'measured', imu_yaw_sign: 1,
    linear_m_s: { '1': .2 }, turn_rad_s: { '20': .4 } });
  assert.equal(model.profileError(profile), 'manual_measurement_evidence_required');
  profile.measurements = [{ measurement_id: 'measured', notes: 'fictional test evidence', status: 'failed' }];
  assert.equal(model.profileError(profile), null);
  profile.provenance.kind = 'historical'; assert.equal(model.profileError(profile), 'manual_measurement_evidence_required');
});
test('whole-trial average is displayed separately and never promotes a measured table', () => {
  const trial = { kind: 'linear', distance_m: .2, duration_s: 2, phase: 'complete' };
  assert.equal(model.trialAverage(trial), .1); assert.equal(trial.phase, 'complete');
  assert.equal(model.trialAverage({ ...trial, duration_s: 0 }), null);
  assert.equal(model.trialAverage({ ...trial, distance_m: null }), null);
});
test('fresh DISARMED supports initial legacy profile and partial recovery without requiring model ready', () => {
  assert.equal(model.activationAllowed(runtime(), safe(), true, now), true);
  const row = runtime(); row.error = 'active_profile_unavailable'; row.status = 'partial';
  row.motion.ready = false; row.odometry.pose = { data_ready: false, error: 'manual_calibration_required' };
  assert.equal(model.activationAllowed(row, { ...safe(), ready: false }, true, now), true);
  for (const patch of [{ state: 'ARMED' }, { generation: 'other' }, { observed_at: null }, { observed_at: now - 4 }]) {
    assert.equal(model.activationAllowed(row, { ...safe(), ...patch }, true, now), false);
  }
  assert.equal(model.activationAllowed(row, safe(), false, now), false);
  row.motion.output.lx = .001; assert.equal(model.activationAllowed(row, safe(), true, now), false);
});
test('configuration applied is separate from physical completion and unverified odometry model', () => {
  const value = model.activationView(applied(), digest, now);
  assert.equal(value.applied, true); assert.equal(value.modelReady, false); assert.equal(value.confirmation, 'executed');
  assert.equal(value.modelError, 'manual_calibration_required');
});
test('missing, partial, stale, mismatched or pending confirmation never becomes applied', () => {
  const initial = applied();
  for (const changed of [
    { ...initial, status: 'pending' }, { ...initial, stale: true }, { ...initial, error: 'partial' },
    { ...initial, motion: { ...initial.motion, observed_at: now - 4 } },
    { ...initial, odometry: { ...initial.odometry, observed_at: null } },
    { ...initial, odometry: { ...initial.odometry, calibration: { ...initial.odometry.calibration, profile_digest: 'b'.repeat(64) } } },
    { ...initial, motion: { ...initial.motion, calibration: { ...initial.motion.calibration, applied_ack: null } } },
  ]) assert.equal(model.activationView(changed, digest, now).applied, false);
});
test('fresh saved consumer hashes do not invent ACK or reuse an unrelated last rejection', () => {
  const row = applied(); row.confirmation = 'loaded_from_saved';
  row.motion.calibration.source = row.odometry.calibration.source = 'saved_profile';
  row.motion.calibration.applied_ack = null;
  row.motion.calibration.applied_generation = row.odometry.calibration.applied_generation = null;
  row.motion.calibration.activation_request_id = row.odometry.calibration.activation_request_id = null;
  row.motion.calibration.last_ack = { status: 'rejected', request_id: 'unrelated' };
  assert.equal(model.activationView(row, digest, now).applied, true);
  row.odometry.calibration.motion_instance_id = 'old-process'; assert.equal(model.activationView(row, digest, now).applied, false);
});
test('pulse rejects unknown, nonfinite, empty, zero and out-of-bounds values', () => {
  assert.deepEqual(model.pulseValues('.1', '0', '.1'), { vx: .1, yaw: 0, duration: .1 });
  for (const args of [['', '0', '.1'], ['0', '0', '.1'], ['NaN', '0', '.1'], ['2', '0', '.1'], ['.1', '0', '.3']])
    assert.throws(() => model.pulseValues(...args));
});
test('reference requires exact terminal ACK and observed reference/HOME, not transport 202', () => {
  const command = { request_id: 'ref', source: 'manual', seq: 9, generation, ts: now - 1, home_operator_confirmed: true, home_x: 1, home_y: 2 };
  const snapshot = { contract_version: 1, observed_at: now, instance_id: 'odom', actuation: false, reference_verified: true,
    reference_id: 'ref', home: { operator_confirmed: true, reference_id: 'ref', x: 1, y: 2 },
    last_ack: { observed_at: now - .5, request_id: 'ref', source: 'manual', seq: 9, command_generation: generation,
      instance_id: 'odom', action: 'reference', status: 'executed', accepted: true, actuation: false } };
  assert.equal(model.referenceConfirmed(snapshot, command, now), true);
  for (const changed of [{ ...snapshot, last_ack: null }, { ...snapshot, reference_verified: false },
    { ...snapshot, home: { ...snapshot.home, x: 0 } }, { ...snapshot, observed_at: now - 4 }])
    assert.equal(model.referenceConfirmed(changed, command, now), false);
});

class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.listeners = {}; this.value = ''; this.checked = false;
    this.disabled = false; this.dataset = {}; this.nodeType = 1; this.parent = null; this.textContent = ''; }
  get value() { return this._value ?? ''; }
  set value(value) { this._value = String(value); }
  append(...nodes) { for (const node of nodes) { this.children.push(node); node.parent = this; } }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelector(selector) {
    const key = selector === '[data-step]' ? 'step' : selector === '[data-rate]' ? 'rate' : null;
    for (const child of this.children) {
      if ((key && Object.hasOwn(child.dataset, key)) || child.tag === selector) return child;
      const found = child.querySelector(selector); if (found) return found;
    } return null;
  }
  remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); }
}
async function fixture() {
  const html = await readFile(path.join(root, 'web/calibration.html'), 'utf8');
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element()]));
  const calls = [], moves = []; let current = runtime(), moment = now, counter = 0;
  const find = (node, id) => node.id === id ? node : node.children.map(child => find(child, id)).find(Boolean);
  const document = { getElementById: id => elements.get(id) || [...elements.values()].map(node => find(node, id)).find(Boolean), createElement: tag => new Element(tag) };
  const el = (tag, css = '', value) => { const node = new Element(tag); node.textContent = value ?? ''; return node; };
  const ctx = vm.createContext({ ...model, document, structuredClone, TextEncoder, Date, Math, Number, String, Object,
    JSON, Promise, Boolean, Error, window: { addEventListener() {} }, setTimeout() {}, globalThis: { crypto: { randomUUID: () => counter++ === 0 ? 'fixture-request' : 'fixture-request-' + counter } },
    nowSeconds: () => moment, commandSeconds: () => moment, el, tr: pl => pl, ageLabel: () => '0 s', kv: () => new Element(),
    button: (title, callback) => { const node = new Element('button'); node.listeners.click = callback; return node; },
    text: (id, value) => { elements.get(id).textContent = value; }, showError() {},
    request: async (route, options = {}) => {
      calls.push({ route, ...options });
      if (route === '/api/calibration/state') return { data: current, status: 200 };
      if (route === '/api/calibration/profiles') return { data: { schema_version: 1, profiles: [] }, status: 200 };
      return { data: { pending: true, status: 'pending' }, status: 202 };
    },
    poll: load => { load(); return { refresh: load, stop() {} }; } });
  const source = (await readFile(path.join(root, 'web/assets/operator/calibration.js'), 'utf8'))
    .replace(/^import[\s\S]*?;\n/gm, '').replace('export class Calibration', 'globalThis.Calibration = class Calibration');
  vm.runInContext(source, ctx);
  const safety = { state: safe(), seq: 4, update(state) { this.state = state; }, clockFresh: () => true, can: () => true,
    send: async (action, body) => { moves.push({ action, body }); return { pending: true }; } };
  const panel = new ctx.globalThis.Calibration(safety);
  await new Promise(resolve => setImmediate(resolve));
  return { panel, elements, calls, moves, setTime: value => { moment = value; }, setState: row => { current = row; panel.state = row; } };
}
test('opening and polling the page never mutates, starts services or repeatedly reads revisions', async () => {
  const row = await fixture();
  assert.equal(row.calls.every(call => !call.method || call.method === 'GET'), true);
  assert.equal(row.moves.length, 0);
  const catalogs = () => row.calls.filter(call => call.route === '/api/calibration/profiles').length;
  assert.equal(catalogs(), 1); await row.panel.load(); await row.panel.load(); assert.equal(catalogs(), 1);
});
test('activation creates one original DISARMED envelope and stays pending after 202', async () => {
  const row = await fixture();
  row.elements.get('calibration-revision').value = digest;
  row.elements.get('calibration-activation-plan').value = 'fake configuration plan';
  row.elements.get('calibration-activation-consent').checked = true;
  await row.panel.activate();
  const call = row.calls.find(value => value.method === 'POST');
  assert.equal(call.route, '/api/calibration/activate'); assert.equal(call.body.generation, generation);
  assert.equal(call.body.seq, 5); assert.equal(call.body.ts, now); assert.equal(call.body.ttl_ms, 500);
  assert.equal(row.panel.awaiting.request_id, 'fixture-request');
  assert.equal(row.elements.get('calibration-activation-consent').checked, false);
  assert.equal(row.moves.length, 0); await row.panel.activate();
  assert.equal(row.calls.filter(value => value.method === 'POST').length, 1);
});
test('single pulse requires fresh consent every attempt and never starts ARM', async () => {
  const row = await fixture();
  for (const [key, value] of [['pulse-vx', '.1'], ['pulse-yaw', '0'], ['pulse-duration', '.1'], ['pulse-plan', 'fake one trial']])
    row.elements.get(key).value = value;
  await assert.rejects(row.panel.pulse(), /explicit_single_trial_consent_required/);
  row.elements.get('pulse-consent').checked = true; await row.panel.pulse();
  assert.equal(row.elements.get('pulse-consent').checked, false); assert.equal(row.moves.length, 1);
  assert.equal(row.moves[0].action, 'move'); await assert.rejects(row.panel.pulse());
  assert.equal(row.moves.length, 1); assert.equal(row.calls.some(call => call.route === '/api/safety'), false);
});
test('profile form preserves unknown historical condition and observation structures', async () => {
  const row = await fixture(), profile = model.defaultProfile(); profile.name = 'history';
  profile.odometry.conditions.special_surface_note = 'preserve me';
  profile.odometry.observations.acceleration = { duration_s: 1, note: 'raw evidence' };
  profile.odometry.observations.custom_raw = { signed: -1 };
  row.panel.loadProfile(profile);
  const saved = row.panel.buildProfile();
  assert.equal(saved.odometry.conditions.special_surface_note, 'preserve me');
  assert.deepEqual(saved.odometry.observations.acceleration, profile.odometry.observations.acceleration);
  assert.deepEqual(saved.odometry.observations.custom_raw, profile.odometry.observations.custom_raw);
  assert.equal(saved.odometry.manual_verified, false);
});

test('correlated 202 rejection releases pending for a new explicit operator request', async () => {
  const row = await fixture();
  row.elements.get('calibration-revision').value = digest;
  row.elements.get('calibration-activation-plan').value = 'one configuration attempt';
  row.elements.get('calibration-activation-consent').checked = true;
  await row.panel.activate(); const command = row.panel.awaiting;
  row.setState({ ...runtime(), status: 'partial', error: 'profile_rejected', requested: { ...command } });
  row.panel.render(); assert.equal(row.panel.awaiting, null);
  assert.match(row.elements.get('calibration-activation-result').textContent, /partial.*profile_rejected/);
  await assert.rejects(row.panel.activate(), /consent/);
  row.elements.get('calibration-activation-consent').checked = true; await row.panel.activate();
  assert.equal(row.calls.filter(call => call.method === 'POST').length, 2);
  assert.equal(row.panel.awaiting.seq, 6); assert.notEqual(row.panel.awaiting.request_id, command.request_id);
  assert.equal(row.moves.length, 0);
});
test('ambiguous timeout stays unknown but fresh state permits another explicit request', async () => {
  const row = await fixture();
  row.elements.get('calibration-revision').value = digest;
  row.elements.get('calibration-activation-plan').value = 'one configuration attempt';
  row.elements.get('calibration-activation-consent').checked = true; await row.panel.activate();
  row.setTime(now + 9);
  const state = runtime(); state.motion.observed_at = state.odometry.observed_at = now + 9;
  row.panel.safety.state = { ...safe(), observed_at: now + 9 }; row.setState(state);
  row.panel.render(); assert.equal(row.panel.awaiting, null);
  assert.match(row.elements.get('calibration-activation-result').textContent, /unknown.*timeout/);
  assert.equal(row.elements.get('activate-calibration').disabled, false);
  assert.equal(row.calls.filter(call => call.method === 'POST').length, 1);
  row.elements.get('calibration-activation-consent').checked = true; await row.panel.activate();
  assert.equal(row.calls.filter(call => call.method === 'POST').length, 2);
});
test('reference denies old consumer after profile change and correlates expected profile digest', async () => {
  const row = await fixture(); row.setState(applied());
  assert.equal(row.panel.referenceAllowed(), true);
  const stale = applied(); stale.odometry.calibration.profile_digest = 'b'.repeat(64);
  row.setState(stale); assert.equal(row.panel.referenceAllowed(), false);
  const command = { request_id: 'ref', source: 'manual', seq: 9, generation, ts: now - 1, profile_digest: digest };
  const snapshot = { contract_version: 1, observed_at: now, instance_id: 'odom', actuation: false,
    reference_verified: true, reference_id: 'ref', calibration: { profile_digest: digest }, pose: { calibration_id: digest },
    last_ack: { observed_at: now - .5, request_id: 'ref', source: 'manual', seq: 9, command_generation: generation,
      instance_id: 'odom', action: 'reference', status: 'executed', accepted: true, actuation: false, profile_digest: digest } };
  assert.equal(model.referenceConfirmed(snapshot, command, now), true);
  snapshot.pose.calibration_id = 'old'; assert.equal(model.referenceConfirmed(snapshot, command, now), false);
});
