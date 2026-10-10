// Runs in Node's isolated VM. fetch is fixture-only; no socket or SDK exists.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const assets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../web/assets/operator');
const model = await import(`data:text/javascript;base64,${Buffer.from(await readFile(path.join(assets, 'model.js'))).toString('base64')}`);
const instant = Date.now() / 1000;
const capability = { available: true, stop_verified: true };
const armed = () => ({ contract_version: 1, state: 'ARMED', generation: 'fixture-generation', owner: 'manual',
  ready: true, hardware_ready: true, can_move: true, read_only: false, observed_at: Date.now() / 1000, lease_remaining_s: 10, last_seq: 4,
  capabilities: { move: capability, turn: capability, height: { available: false, stop_verified: false, verification: 'manual_characterization_required' } } });
const disarmed = () => ({ ...armed(), state: 'DISARMED', owner: null, can_move: false, read_only: true });

test('movement requires version, fresh observation, state, owner, lease and stop capability', () => {
  const state = armed();
  assert.equal(model.authorized(state, 'manual', 'move', instant), true);
  for (const patch of [{ contract_version: 0 }, { observed_at: instant - 4 }, { observed_at: null },
    { state: 'DISARMED' }, { ready: false }, { hardware_ready: false }, { can_move: false }, { read_only: true },
    { owner: 'navigation' }, { lease_remaining_s: 0 }, { lease_remaining_s: 31 }, { lease_remaining_s: Infinity }, { generation: '' },
    { capabilities: { move: { available: true, stop_verified: false } } }]) {
    assert.equal(model.authorized({ ...state, ...patch }, 'manual', 'move', instant), false, JSON.stringify(patch));
  }
  assert.equal(model.authorized(state, 'manual', 'height', instant), false);
});
test('DISARMED read_only is a valid known contract for explicit preparation', () => {
  assert.equal(model.safetyKnown(disarmed()), true);
  assert.equal(model.authorized(disarmed(), 'manual'), false);
});
test('zero is a measurement; null and stale frame timestamps remain unknown', () => {
  assert.equal(model.displayValue(0, '%'), '0%');
  assert.equal(model.displayValue(null), '—');
  assert.equal(model.cameraFrame({ raw: { exists: true, mtime: instant - 20 } }, 'raw', instant).fresh, false);
  assert.equal(model.cameraFrame({ raw: { exists: true, mtime: null } }, 'raw', instant).age, null);
  for (const flags of [{ offline: true }, { stale: true }, { error: 'camera unavailable' }]) {
    assert.equal(model.cameraFrame({ ...flags, raw: { exists: true, mtime: instant } }, 'raw', instant).fresh, false);
  }
  assert.equal(model.cameraFrame({ raw: { exists: true, stale: true, mtime: instant } }, 'raw', instant).fresh, false);
});
test('old catalog and moving owner mismatch cannot start a task', () => {
  const task = { installed: true, observed_at: instant, state: 'stopped', can_move: true, motion_owner: 'navigation' };
  const catalog = { contract_version: 2, catalog_version: 2, observed_at: instant, features: [task], units: [] };
  assert.equal(model.taskCanStart(task, catalog, armed(), instant), false);
  assert.equal(model.taskCanStart(task, { ...catalog, contract_version: 1 }, { ...armed(), owner: 'navigation' }, instant), false);
  assert.equal(model.taskCanStart(task, catalog, { ...armed(), owner: 'navigation' }, instant), true);
  for (const can_move of [undefined, null]) assert.equal(model.taskCanStart({ ...task, can_move }, catalog, armed(), instant), false);
  assert.equal(model.taskCanStart({ ...task, can_move: false }, { ...catalog, offline: true }, armed(), instant), false);
});
test('ACK matches action, source, sequence, request and send time; accepted is not execution', () => {
  const command = { request_id: 'fixture', action: 'move', source: 'manual', seq: 5, generation: 'fixture-generation' };
  const ack = { ...command, observed_at: instant, status: 'executed' };
  assert.equal(model.matchingAck(ack, command, instant), true);
  for (const patch of [{ observed_at: instant - .1 }, { status: 'accepted' }, { action: 'stop' }, { seq: 4 }, { source: 'navigation' }, { command_generation: 'another-generation' }]) {
    assert.equal(model.matchingAck({ ...ack, ...patch }, command, instant), false);
  }
});
test('confirmed HTTP ACK uses backend identity confirmation; STOP null sequence is equivalent to absent', () => {
  const command = { request_id: 'stop-fixture', action: 'stop', source: 'manual' };
  const ack = { ...command, seq: null, observed_at: instant - 1, status: 'executed' };
  assert.equal(model.matchingAck(ack, command, instant), false);
  assert.equal(model.matchingAck(ack, command, instant, true), true);
  assert.equal(model.matchingAck({ ...ack, request_id: 'another-request' }, command, instant, true), false);
});
test('server clock bounds tolerate skew without future commands or understating observation age', () => {
  const wall = Date.now() / 1000;
  assert.equal(model.setServerClock(wall + 20, wall - .3, wall), true);
  assert.ok(model.commandSeconds() <= wall + 20.1);
  assert.ok(model.nowSeconds() >= wall + 20.3);
  assert.equal(model.setServerClock(wall + 20, wall - .51, wall), false);
  assert.equal(model.setServerClock(null, wall, wall), false);
  model.setServerClock(Date.now() / 1000, Date.now() / 1000, Date.now() / 1000);
});
test('map world coordinates use mapper additive origin and preserve zero', () => {
  assert.deepEqual(model.gridPoint({ origin_x: 5, origin_y: 3, resolution_m: .1 }, { x: 0, y: 0 }), [50, 30]);
  assert.equal(model.gridPoint({ origin_x: null, origin_y: 3, resolution_m: .1 }, [0, 0]), null);
  assert.equal(model.gridPoint({ origin_x: 1e308, origin_y: 0, resolution_m: .1 }, [1e308, 0]), null);
});

class Element {
  constructor(id = '') { this.id = id; this.listeners = {}; this.value = ''; this.checked = false; this.disabled = false; this.dataset = {}; this.children = []; this.nodeType = 1; this.classList = { toggle() {}, add() {} }; }
  addEventListener(name, action) { this.listeners[name] = action; }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  closest(selector) { return this.editing && selector.includes('input') ? this : null; }
}
async function fixture(initial = disarmed()) {
  const elements = new Map(['arm', 'clear-estop', 'disarm', 'estop', 'operator-plan', 'operator-consent', 'control-owner', 'lease',
    'duration', 'speed', 'yaw-speed', 'request-history', 'safety-state', 'safety-owner', 'safety-reason', 'safety-lease', 'operator-message'].map(id => [id, new Element(id)]));
  elements.get('control-owner').value = 'manual'; elements.get('lease').value = '10'; elements.get('duration').value = '.1';
  elements.get('speed').value = '.1'; elements.get('yaw-speed').value = '.18';
  const listeners = {}, timers = new Map(), calls = [];
  let timerId = 0, current = initial; const replies = new Map();
  const document = { hidden: false, documentElement: { lang: 'pl' }, body: { dataset: { page: 'control' } },
    getElementById: id => elements.get(id), querySelector: () => null, querySelectorAll: () => [], createElement: () => new Element(),
    addEventListener: (name, action) => { listeners[name] = action; }, removeEventListener() {} };
  const context = vm.createContext({ document, window: { addEventListener() {} }, console,
    Date, Math, Number, String, Boolean, JSON, Map, Set, Error, AbortController,
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; }, clearTimeout: id => timers.delete(id),
    setInterval: callback => { timers.set(++timerId, callback); return timerId; }, clearInterval: id => timers.delete(id),
    fetch: async (url, options) => {
      calls.push({ url, ...options, body: options.body ? JSON.parse(options.body) : undefined });
      return { ok: true, status: options.method === 'POST' ? 202 : 200,
        json: async () => replies.has(url) ? replies.get(url) : options.method === 'POST' ? { pending: true, confirmed: false } : { safety: current, server_time: Date.now() / 1000 } };
    } });
  const modules = new Map();
  async function load(name) {
    if (modules.has(name)) return modules.get(name);
    const source = await readFile(path.join(assets, name), 'utf8');
    const module = new vm.SourceTextModule(source, { context, identifier: name }); modules.set(name, module);
    await module.link(specifier => load(path.basename(specifier)));
    return module;
  }
  const module = await load('safety.js'); await module.evaluate();
  const panel = new module.namespace.SafetyPanel();
  await new Promise(resolve => setImmediate(resolve));
  return { panel, elements, calls, listeners, document, timers, setReply(url, data) { replies.set(url, data); }, async load(name) { const module = await load(name); await module.evaluate(); return module.namespace; }, setState(value) { current = value; panel.update(value); } };
}

test('opening control issues GET only and permits explicit ARM from known DISARMED', async () => {
  const f = await fixture();
  assert.ok(f.calls.length > 0);
  assert.ok(f.calls.every(call => call.method === 'GET'));
  assert.equal(f.elements.get('arm').disabled, false);
  assert.equal(f.elements.get('clear-estop').disabled, true);
});
test('typing, select, repeated key and modifier do not issue movement', async () => {
  const f = await fixture(armed());
  const input = new Element(); input.editing = true;
  for (const code of ['KeyW', 'ArrowLeft', 'Space']) f.panel.key({ code, target: input, preventDefault() { throw new Error('typing intercepted'); } });
  f.panel.key({ code: 'KeyW', target: new Element(), repeat: true });
  f.panel.key({ code: 'KeyW', target: new Element(), ctrlKey: true });
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
});
test('wrong owner, stale contract and non-control view do not issue movement', async () => {
  const f = await fixture({ ...armed(), owner: 'navigation' });
  f.panel.key({ code: 'KeyW', target: new Element() });
  f.setState({ ...armed(), observed_at: Date.now() / 1000 - 4 }); f.panel.move('forward');
  f.setState(armed()); f.document.body.dataset.page = 'view'; f.panel.key({ code: 'KeyW', target: new Element() });
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
});
test('explicit arm carries one fresh envelope, plan and consent; never auto arms', async () => {
  const f = await fixture();
  f.elements.get('operator-plan').value = 'Przestrzeń wolna, kabel zabezpieczony, impuls 0.1 s.';
  f.elements.get('operator-consent').checked = true;
  await f.panel.arm('arm');
  const commands = f.calls.filter(call => call.method === 'POST'); assert.equal(commands.length, 1);
  const body = commands[0].body;
  assert.equal(commands[0].url, '/api/safety'); assert.equal(body.action, 'arm');
  assert.equal(body.generation, 'fixture-generation'); assert.equal(body.seq, 5); assert.equal(body.ttl_ms, 500);
  assert.equal(body.operator_consent, true); assert.ok(body.operator_plan); assert.ok(body.ts > instant - 1);
  assert.equal(f.elements.get('operator-consent').checked, false);
});
test('202 remains pending until exact terminal ACK; stale/accepted ACK cannot turn green', async () => {
  const f = await fixture(armed()); await f.panel.send('move', { vx: .1, yaw: 0, duration: .1 });
  const entry = f.panel.history[0]; assert.equal(entry.status, 'pending');
  f.panel.ack({ ...entry.command, observed_at: entry.submittedAt, status: 'accepted' }); assert.equal(entry.status, 'pending');
  f.panel.ack({ ...entry.command, observed_at: entry.submittedAt - 1, status: 'executed' }); assert.equal(entry.status, 'pending');
  f.panel.ack({ ...entry.command, observed_at: entry.submittedAt, status: 'executed', physical_completion: 'unverified' });
  assert.equal(entry.status, 'executed'); assert.equal(entry.ack.physical_completion, 'unverified');
});
test('STOP works without safety metadata while disconnected', async () => {
  const f = await fixture(null); await f.panel.send('stop');
  const command = f.calls.find(call => call.method === 'POST').body;
  assert.equal(command.action, 'stop'); assert.equal(command.generation, undefined); assert.equal(command.seq, undefined);
});
test('focus/connection loss sends STOP and immediately removes authority', async () => {
  const f = await fixture(armed()); f.panel.suspend();
  assert.equal(f.panel.state, null); assert.equal(f.panel.can(), false);
  assert.equal(f.calls.find(call => call.method === 'POST').body.action, 'stop');
  f.setState(armed()); assert.equal(f.panel.can(), false, 'same generation must not recover on reconnect');
});
test('explicit STOP immediately removes authority before a response, with no implicit rearm', async () => {
  const f = await fixture(armed()); await f.panel.send('stop');
  assert.equal(f.panel.can(), false);
  await assert.rejects(f.panel.send('move', { vx: .1, yaw: 0, duration: .1 }));
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
});
test('hardware fault prevents ARM although the state is known DISARMED', async () => {
  const f = await fixture({ ...disarmed(), hardware_ready: false });
  f.elements.get('operator-plan').value = 'Prepared fixture'; f.elements.get('operator-consent').checked = true;
  assert.equal(f.elements.get('arm').disabled, true); await f.panel.arm('arm');
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
});
test('out of range, blank and nonfinite pulse values never produce an HTTP mutation', async () => {
  const f = await fixture(armed());
  for (const params of [{ vx: .1, yaw: 0, duration: 1 }, { vx: NaN, yaw: 0, duration: .1 }, { vx: 2, yaw: 0, duration: .1 }]) await assert.rejects(f.panel.send('move', params));
  f.elements.get('speed').value = ''; f.panel.move('forward');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
});
test('navigation view reads only; explicit owner matching start preserves click envelope and 202 pending', async () => {
  const f = await fixture({ ...armed(), owner: 'navigation' });
  for (const id of ['nav-strategy', 'nav-speed', 'nav-turn', 'nav-start', 'nav-return_home', 'nav-stop', 'nav-config']) f.elements.set(id, new Element(id));
  f.elements.get('nav-strategy').value = 'STOP';
  const { Navigation } = await f.load('navigation.js'); const navigation = new Navigation(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(f.calls.every(call => call.method === 'GET'));
  await navigation.command('start');
  const post = f.calls.find(call => call.method === 'POST');
  assert.equal(post.url, '/api/navigator/start'); assert.equal(post.body.source, 'manual');
  assert.equal(post.body.generation, 'fixture-generation'); assert.equal(post.body.ttl_ms, 500);
  assert.equal(post.body.action, undefined); assert.ok(post.body.request_id);
  const entry = navigation.history[0]; assert.equal(entry.status, 'pending');
  const runtime = { active: true, state: 'EXPLORING', observed_at: Date.now() / 1000, generation: entry.generation, request_id: entry.request_id };
  navigation.observeRequest({ ...runtime, request_id: 'another-request' }); assert.equal(entry.status, 'pending');
  navigation.observeRequest(runtime); assert.equal(entry.status, 'task_observed');
  f.setState({ ...armed(), owner: 'manual' }); await navigation.command('return_home');
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
});
test('System is GET-only until explicit administration and a fresh, known unit action', async () => {
  const f = await fixture();
  for (const id of ['service-list', 'admin-mode', 'rescue-resource', 'rescue-consent', 'rescue-confirm', 'rescue-release']) f.elements.set(id, new Element(id));
  const { System } = await f.load('system.js'); const system = new System(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(f.calls.every(call => call.method === 'GET')); assert.equal(system.admin, false);
  const row = { unit: 'fixture.service', can_move: false, load: 'loaded', observed_at: Date.now() / 1000 };
  await system.action(row, 'start'); assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
  system.admin = true; system.catalog = { contract_version: 2, catalog_version: 2, features: [], units: [], observed_at: Date.now() / 1000 };
  system.services = { contract_version: 2, services: [], observed_at: Date.now() / 1000 };
  await system.action({ ...row, can_move: undefined }, 'start'); assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
  await system.action(row, 'start'); assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(f.calls.find(call => call.method === 'POST').url, '/svc/fixture.service');
});
test('device reads and preview toggle do not start capture or make an unknown frame visible', async () => {
  const f = await fixture();
  for (const id of ['camera-image', 'device-list', 'preview-kind', 'preview-url', 'preview-toggle']) f.elements.set(id, new Element(id));
  f.elements.get('preview-kind').value = 'raw';
  const { Devices } = await f.load('devices.js'); const devices = new Devices();
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(f.calls.every(call => call.method === 'GET')); assert.equal(f.elements.get('camera-image').src, undefined);
  f.elements.get('preview-toggle').listeners.click(); assert.equal(devices.preview, true);
  f.elements.get('preview-toggle').listeners.click(); assert.equal(devices.preview, false);
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
});
test('chat viewing reads providers; explicit send requests only text domain and waits if pending', async () => {
  const f = await fixture();
  for (const id of ['chat-provider', 'chat-input', 'chat-send', 'chat-tts']) f.elements.set(id, new Element(id));
  const tasks = { safety: f.panel, options: new Map(), poller: { refresh() {} }, catalog: {
    contract_version: 2, catalog_version: 2, observed_at: Date.now() / 1000, units: [], features: [{
      name: 'fixture-provider', option_kind: 'provider', can_move: false, state: 'stopped', installed: true,
      observed_at: Date.now() / 1000, option_schema: { field: 'domain', choices: [{ value: 'text' }] }, options: {} }] } };
  const { Chat } = await f.load('chat.js'); const chat = new Chat(tasks);
  await new Promise(resolve => setImmediate(resolve)); assert.ok(f.calls.every(call => call.method === 'GET'));
  f.elements.get('chat-input').value = 'Isolated fixture'; await chat.send();
  const posts = f.calls.filter(call => call.method === 'POST'); assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/api/logic/feature/fixture-provider'); assert.equal(posts[0].body.options.domain, 'text');
  assert.equal(f.calls.some(call => call.url === '/api/chat/send'), false);
});

test('poll never overlaps and waits while the page is hidden', async () => {
  const source = await readFile(path.join(assets, 'transport.js'), 'utf8');
  let resolve, loads = 0; const timers = new Map(); const document = { hidden: false, addEventListener() {}, removeEventListener() {} };
  const context = vm.createContext({ document, Date, AbortController, setTimeout: action => { timers.set(timers.size + 1, action); return timers.size; }, clearTimeout: id => timers.delete(id) });
  const module = new vm.SourceTextModule(source, { context }); await module.link(() => {}); await module.evaluate();
  const poller = module.namespace.poll(() => { loads++; return new Promise(done => { resolve = done; }); });
  await poller.refresh(); assert.equal(loads, 1); resolve(); await new Promise(done => setImmediate(done));
  document.hidden = true; await poller.refresh(); assert.equal(loads, 1); poller.stop();
});

test('navigation measurement usability does not hide a fresh failed task status', () => {
  const row = { observed_at: Date.now() / 1000, quality: 'measured' };
  assert.equal(model.presentationReady(row), true);
  for (const flags of [{ stale: true }, { offline: true }, { error: 'sensor failed' },
    { data_ready: false }, { navigation_ready: false }, { data_error: 'not calibrated' },
    { quality: 'unknown' }, { quality: 'error' }, { quality: null }, { quality: 'UNKNOWN' }]) {
    assert.equal(model.presentationReady({ ...row, ...flags }), false, JSON.stringify(flags));
  }
  const failed = { ...row, state: 'FAILED', active: false, data_ready: false };
  assert.equal(model.fresh(failed), true);
  assert.equal(model.presentationReady(failed), false);
});
test('navigation normalization preserves source time and expires unknown packets', () => {
  const observed = Date.now() / 1000, previous = { x: 0, y: 0, theta: 0, observed_at: observed };
  assert.equal(model.navigationObservation({ x: 1, observed_at: observed - 1 }, previous), previous);
  const changed = model.navigationObservation({ ...previous, quality: 'unknown', data_ready: false }, previous);
  assert.equal(changed.observed_at, observed);
  const failure = model.navigationObservation({ error: 'lost', observed_at: observed - 1 }, previous);
  assert.equal(failure.error, 'lost');
  assert.equal(model.presentationReady(failure), false);
  assert.equal(model.presentationReady(changed), false);
  for (const packet of [null, 'bad', [], { error: 'lost' }, { observed_at: null, ts: observed }]) {
    const unknown = model.navigationObservation(packet, previous);
    assert.equal(unknown.observed_at, null);
    assert.equal(unknown.x, undefined);
    assert.equal(model.presentationReady(unknown), false);
  }
});
test('navigation quality changes at the same timestamp redraw and unknown events expire geometry', async () => {
  const f = await fixture(), paints = [];
  for (const id of ['nav-strategy', 'nav-speed', 'nav-turn', 'nav-start', 'nav-return_home', 'nav-stop', 'nav-config',
    'map-age', 'pose-age', 'path-age', 'nav-status']) f.elements.set(id, new Element(id));
  const context = { globalAlpha: 1, fillStyle: '', fillRect() { paints.push([this.fillStyle, this.globalAlpha]); },
    save() {}, restore() {}, translate() {}, rotate() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() {}, fill() {} };
  const canvas = new Element('map-canvas'); canvas.clientWidth = 600; canvas.getContext = () => context;
  f.elements.set('map-canvas', canvas);
  const ts = Date.now() / 1000;
  const map = { width_cells: 2, height_cells: 1, grid: [0,255], resolution_m: .1, origin_x: 0, origin_y: 0,
    observed_at: ts, quality: 'measured' };
  f.setReply('/api/navigator/status', { observed_at: ts, state: 'IDLE', active: false, data_ready: false,
    navigation: { map, pose: null, path: null } });
  const { Navigation } = await f.load('navigation.js'), navigation = new Navigation(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(f.elements.get('nav-status').textContent.includes('IDLE'));
  assert.equal(model.presentationReady(navigation.map), true);
  const key = navigation.drawKey, before = paints.length;
  navigation.event({ topic: 'mapper.map.data', data: { ...map, data_ready: false, quality: 'unknown' } });
  assert.notEqual(navigation.drawKey, key);
  assert.ok(paints.length > before);
  assert.equal(paints.at(-1)[1], .45);
  assert.ok(f.elements.get('map-age').textContent.includes('unavailable'));
  navigation.event({ topic: 'mapper.map.data', data: { error: 'lost', observed_at: null, ts } });
  assert.equal(navigation.map.grid, undefined);
  assert.equal(navigation.map.observed_at, null);
  navigation.event({ topic: 'robot.pose', data: 'broken-json' });
  assert.equal(navigation.pose.x, undefined);
  assert.equal(model.presentationReady(navigation.pose), false);
  f.setReply('/api/navigator/status', { observed_at: ts, state: 'FAILED', active: false, data_ready: false, navigation: null });
  await navigation.poller.refresh();
  assert.equal(navigation.map.grid, undefined);
  assert.ok(f.elements.get('nav-status').textContent.includes('FAILED'));
  assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('posture controls retain canonical envelopes and require verified capabilities', async () => {
  const f = await fixture(armed());
  await assert.rejects(f.panel.send('height', { height: 6 }));
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
  f.setState({ ...armed(), capabilities: { move: capability, turn: capability, height: capability, balance: capability } });
  await f.panel.send('height', { height: 6 });
  await f.panel.send('balance', { enabled: false });
  const posts = f.calls.filter(call => call.method === 'POST');
  assert.equal(posts.length, 2);
  assert.ok(posts.every(call => call.url === '/api/control' && call.body.generation === 'fixture-generation'
    && call.body.source === 'manual' && call.body.ttl_ms === 500 && Number.isFinite(call.body.ts)));
  assert.equal(posts[0].body.action, 'height'); assert.equal(posts[0].body.height, 6);
  assert.equal(posts[1].body.action, 'balance'); assert.equal(posts[1].body.enabled, false);
});

test('passive task mode comes from catalog choices and never allocates motion authority', async () => {
  const f = await fixture(); f.elements.set('task-list', new Element('task-list'));
  const task = { name: 'fixture-passive', scenario: 'S6', title: 'Fixture passive tracker', can_move: false,
    installed: true, requested: false, state: 'stopped', observed_at: Date.now() / 1000, resources: [], options: {},
    option_schema: { field: 'mode', default: 'face', end_value: 'none', choices: [{ value: 'face' }, { value: 'hand' }, { value: 'none' }] } };
  f.setReply('/api/logic/catalog', { contract_version: 2, catalog_version: 2, observed_at: Date.now() / 1000, features: [task], units: [] });
  const { Tasks } = await f.load('tasks.js'); const tasks = new Tasks(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(f.calls.every(call => call.method === 'GET'));
  tasks.options.set(task.name, { mode: 'hand' }); await tasks.change(task, true);
  tasks.options.set(task.name, { mode: 'none' }); await tasks.change(task, true);
  const posts = f.calls.filter(call => call.method === 'POST');
  assert.equal(posts.length, 2);
  assert.ok(posts.every(call => call.url === '/api/logic/feature/fixture-passive'
    && call.body.generation === undefined && call.body.seq === undefined));
  assert.equal(posts[0].body.options.mode, 'hand'); assert.equal(posts[0].body.enabled, true);
  assert.equal(posts[1].body.options.mode, 'none'); assert.equal(posts[1].body.enabled, false);
});

test('device telemetry does not appear healthy with fresh timestamp and source failure', async () => {
  const f = await fixture();
  for (const id of ['camera-image', 'device-list', 'preview-kind', 'preview-url', 'preview-toggle']) f.elements.set(id, new Element(id));
  f.elements.get('preview-kind').value = 'raw';
  f.setReply('/state', { devices: { xgo: { observed_at: Date.now() / 1000, battery_pct: 0, offline: true, error: 'fixture unavailable' } } });
  const { Devices } = await f.load('devices.js'); const devices = new Devices();
  await devices.load();
  const telemetry = f.elements.get('device-list').children[0];
  assert.ok(telemetry.children[1].className.includes('is-warn'));
  assert.ok(telemetry.children[1].textContent.includes('brak'));
  assert.ok(JSON.stringify(telemetry).includes('0%'));
  assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('resource recovery requires explicit current PID inventory and operator confirmation', async () => {
  const f = await fixture();
  for (const id of ['service-list', 'admin-mode', 'rescue-resource', 'rescue-consent', 'rescue-confirm', 'rescue-release']) f.elements.set(id, new Element(id));
  const { System } = await f.load('system.js'); const system = new System(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  system.catalog = { contract_version: 2, catalog_version: 2, features: [], units: [], observed_at: Date.now() / 1000 };
  system.admin = true;
  f.elements.get('rescue-resource').value = 'camera';
  f.elements.get('rescue-confirm').value = 'camera';
  const selected = new Element(); selected.value = '42';
  f.document.querySelectorAll = () => [selected];
  const busy = { contract_version: 2, state: 'busy', free: false, consumers: [], observed_at: Date.now() / 1000,
    holders: [{ pid: 42, service: 'fixture-camera.service' }] };
  system.resources.set('camera', busy);
  assert.equal(system.rescuePermitted(), false);
  f.elements.get('rescue-consent').checked = true;
  assert.equal(system.rescuePermitted(), true);
  for (const patch of [{ state: 'unknown', free: null }, { state: 'unavailable', free: null }, { free: null },
    { stale: true }, { observed_at: null }, { contract_version: 1 }, { error: 'owners unknown' }, { consumers: ['fixture-task'] }]) {
    system.resources.set('camera', { ...busy, ...patch }); assert.equal(system.rescuePermitted(), false);
  }
  system.resources.set('camera', busy); selected.value = '43';
  assert.equal(system.rescuePermitted(), false);
  selected.value = '42'; await system.release();
  const post = f.calls.find(call => call.method === 'POST');
  assert.equal(post.url, '/api/resource/camera');
  assert.equal(post.body.action, 'release'); assert.equal(post.body.pids[0], 42);
  assert.equal(post.body.force, true); assert.equal(post.body.operator_consent, true);
  assert.equal(f.elements.get('rescue-consent').checked, false);
});
