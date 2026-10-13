// Runs in Node's isolated VM. fetch is fixture-only; no socket or SDK exists.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';

import {assets,model,instant,capability,armed,disarmed,Element,fixture,canonicalReply,catalogReply} from './helpers/operator-fixture.mjs';

test('opening control issues GET only and displays the global disarmed button', async () => {
  const f = await fixture();
  assert.ok(f.calls.length > 0); assert.ok(f.calls.every(call => call.method === 'GET'));
  assert.equal(f.elements.get('global-motion-toggle').disabled, false);
  assert.equal(f.elements.get('global-motion-toggle').textContent, 'Robot rozbrojony');
});

test('legacy safety cannot arm through the global toggle', async () => {
  const f = await fixture(disarmed(), { legacySafety: true });
  assert.equal(f.panel.clockReady, false);
  assert.equal(f.elements.get('global-motion-toggle').disabled, true);
  await f.panel.toggleMotion();
  assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('legacy and unknown catalog responses deny mutation before any POST', async () => {
  const now = Date.now() / 1000;
  const canonical = catalogReply([], now);
  for (const reply of [canonical.data, { ...canonical, meta: { ...canonical.meta, envelope_version: 2 } }]) {
    const f = await fixture(); f.setReply('/api/logic/catalog', reply);
    const { request } = await f.load('transport.js');
    await assert.rejects(request('/api/logic/feature/fixture-passive', { method: 'POST', body: { enabled: true } }),
      /Unsupported|read only/);
    assert.ok(f.calls.some(call => call.url === '/api/logic/catalog' && call.method === 'GET'));
    assert.ok(f.calls.every(call => call.method === 'GET'), 'catalog rejection must precede mutation dispatch');
  }
});
test('a canonical-looking body with wrong MIME cannot authorize mutation', async () => {
  for (const canonicalMime of ['application/json', 'application/vnd.rider.api+json;version=2', '']) {
    const f = await fixture(disarmed(), { canonicalMime });
    const { request } = await f.load('transport.js');
    await assert.rejects(request('/api/logic/feature/fixture-passive', { method: 'POST', body: { enabled: true } }), /Content-Type/);
    assert.ok(f.calls.every(call => call.method === 'GET'));
    assert.equal(f.panel.clockReady, false);
  }
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
  const sentAt = Date.now() / 1000;
  await f.panel.toggleMotion();
  const commands = f.calls.filter(call => call.method === 'POST'); assert.equal(commands.length, 1);
  const body = commands[0].body;
  assert.equal(commands[0].url, '/api/safety'); assert.equal(body.action, 'arm');
  assert.equal(body.generation, 'fixture-generation'); assert.equal(body.seq, 5); assert.equal(body.ttl_ms, 500);
  assert.equal(body.operator_consent, true); assert.ok(body.operator_plan);
  assert.ok(body.ts >= sentAt - .1 && body.ts <= Date.now() / 1000 + .1);
  assert.equal(body.execution_context, 'panel');
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
test('ARM is an explicit request even when execution availability is unconfirmed', async () => {
  const f = await fixture({ ...disarmed(), hardware_ready: false });
  assert.equal(f.elements.get('global-motion-toggle').disabled, false); await f.panel.toggleMotion();
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(f.panel.state.state, 'DISARMED', 'HTTP acceptance is not executor permission');
});

test('out of range, blank and nonfinite pulse values never produce an HTTP mutation', async () => {
  const f = await fixture(armed());
  for (const params of [{ vx: .1, yaw: 0, duration: 1 }, { vx: NaN, yaw: 0, duration: .1 }, { vx: 2, yaw: 0, duration: .1 }]) await assert.rejects(f.panel.send('move', params));
  f.elements.get('speed').value = ''; f.panel.move('forward');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
});
test('passive navigation view never requests ARM, service start or unverified autonomous motion', async () => {
  const f = await fixture({ ...armed(), owner: 'navigation' });
  for (const id of ['nav-strategy', 'nav-speed', 'nav-turn', 'nav-start', 'nav-return_home', 'nav-stop', 'nav-config']) f.elements.set(id, new Element(id));
  f.elements.get('nav-strategy').value = 'STOP';
  const { Navigation } = await f.load('navigation.js'); const navigation = new Navigation(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(f.calls.every(call => call.method === 'GET'));
  await navigation.command('start');
  await navigation.command('return_home');
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
  assert.equal(f.elements.get('nav-start').disabled, true);
  assert.equal(f.elements.get('nav-return_home').disabled, true);
  const entry = { request_id: 'old-explicit-intent', generation: 'fixture-generation', ts: Date.now() / 1000, status: 'pending' };
  navigation.history = [entry];
  const runtime = { active: true, state: 'EXPLORING', observed_at: Date.now() / 1000, generation: entry.generation, request_id: entry.request_id };
  navigation.observeRequest({ ...runtime, request_id: 'another-request' }); assert.equal(entry.status, 'pending');
  navigation.observeRequest(runtime); assert.equal(entry.status, 'task_observed');
  f.setState({ ...armed(), owner: 'manual' }); await navigation.command('return_home');
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
});
test('System is GET-only on entry and permits an explicit fresh known unit action', async () => {
  const f = await fixture();
  for (const id of ['service-list', 'rescue-resource', 'rescue-consent', 'rescue-confirm', 'rescue-release']) f.elements.set(id, new Element(id));
  const { System } = await f.load('system.js'); const system = new System(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(f.calls.every(call => call.method === 'GET'));
  const row = { unit: 'fixture.service', can_move: false, load: 'loaded', observed_at: Date.now() / 1000, permissions: { start: { allowed: true } } };
  system.catalog = { contract_version: 2, catalog_version: 2, features: [], units: [], observed_at: Date.now() / 1000 };
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
  const source = (await readFile(path.join(assets, 'transport.js'), 'utf8')).replace(/^import .*;$/gm, '');
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
  await assert.rejects(f.panel.send('height', { height: 90 }));
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
  f.setState({ ...armed(), capabilities: { move: capability, turn: capability, height: capability, balance: capability } });
  await f.panel.send('height', { height: 90 });
  await f.panel.send('balance', { enabled: false });
  const posts = f.calls.filter(call => call.method === 'POST');
  assert.equal(posts.length, 2);
  assert.ok(posts.every(call => call.url === '/api/control' && call.body.generation === 'fixture-generation'
    && call.body.source === 'manual' && call.body.ttl_ms === 500 && Number.isFinite(call.body.ts)));
  assert.equal(posts[0].body.action, 'height'); assert.equal(posts[0].body.height, 90);
  assert.equal(posts[1].body.action, 'balance'); assert.equal(posts[1].body.enabled, false);
});

test('passive task mode comes from catalog choices and never allocates motion authority', async () => {
  const f = await fixture(); f.elements.set('task-list', new Element('task-list'));
  const task = { name: 'fixture-passive', scenario: 'S6', title: 'Fixture passive tracker', can_move: false,
    installed: true, requested: false, state: 'stopped', observed_at: Date.now() / 1000, resources: [], options: {},
    option_schema: { field: 'mode', default: 'face', end_value: 'none', choices: [{ value: 'face' }, { value: 'hand' }, { value: 'none' }] } };
  f.setReply('/api/logic/catalog', catalogReply([task]));
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

function passiveFixture(now = Date.now() / 1000) {
  const home = { x: 1, y: 0, calibration_id: 'record', reference_id: 'origin', operator_confirmed: true };
  return { observed_at: now, planning_only: true, data_ready: true, navigation_ready: false,
    data_error: 'navigation_traversal_unverified', state: 'path_blocked', active: false,
    plan_observed_at: now - .2, plan_calibration_id: 'record', plan_reference_id: 'origin', plan_home: home,
    goal_pose: [1, 0], planned_path: [[0, 0], [1, 0]], planned_path_length: 2, planned_path_truncated: false };
}
test('point plans preserve original source age and never count as movement readiness', () => {
  const now = Date.now() / 1000, status = passiveFixture(now);
  const plan = model.passivePlanObservation(status, null, now);
  assert.equal(plan.observed_at, status.plan_observed_at);
  assert.equal(model.planningPresentationReady(plan, 3, now), true);
  assert.equal(model.presentationReady(plan, 3, now), false);
  assert.equal(plan.navigation_ready, false); assert.equal(plan.physical_completion, 'unverified');
  const heartbeat = model.passivePlanObservation({ ...status, observed_at: now + 4 }, plan, now + 4);
  assert.equal(heartbeat.observed_at, plan.observed_at);
  assert.equal(model.planningPresentationReady(heartbeat, 3, now + 4), false);
  assert.equal(model.passivePlanObservation({ ...status, plan_observed_at: now - .3 }, plan, now), plan);
});
test('failed, mismatched, oversized or missing plan observations cannot recover through a heartbeat', () => {
  const now = Date.now() / 1000, status = passiveFixture(now), plan = model.passivePlanObservation(status, null, now);
  for (const change of [{ plan_observed_at: null }, { plan_observed_at: now + .1 }, { plan_reference_id: 'old' },
    { plan_home: null }, { goal_pose: [0, 0] }, { planned_path: [] }, { planned_path: Array.from({ length: 129 }, () => [0, 0]) },
    { planned_path: [[NaN, 0]] }, { offline: true }, { error: 'lost' }, { data_ready: false }, { data_error: 'camera_failed' }]) {
    const invalid = model.passivePlanObservation({ ...status, ...change }, plan, now);
    assert.equal(invalid.observed_at, null, JSON.stringify(change));
    assert.equal(model.planningPresentationReady(invalid, 3, now), false);
  }
  const frame = { calibration_id: 'record', reference_id: 'origin', home: status.plan_home };
  assert.equal(model.sameNavigationFrame(frame, plan), true);
  assert.equal(model.sameNavigationFrame({ ...frame, reference_id: 'new' }, plan), false);
  assert.equal(model.sameNavigationFrame({ ...frame, home: { ...frame.home, x: 2 } }, plan), false);
});
test('catalog explicitly unavailable navigation cannot start even with a current operator lease', () => {
  const now = Date.now() / 1000;
  const task = { installed: true, observed_at: now, state: 'stopped', can_move: true, motion_owner: 'navigation', start_available: false };
  const catalog = { contract_version: 2, catalog_version: 2, observed_at: now, features: [task], units: [] };
  assert.equal(model.taskCanStart(task, catalog, { ...armed(now), owner: 'navigation' }, now), false);
});
test('navigation reads passive HOME and plan without ARM or POST and hides a changed frame', async () => {
  const f = await fixture(disarmed());
  for (const id of ['nav-start', 'nav-return_home', 'nav-config', 'nav-stop', 'nav-goal', 'nav-reason', 'nav-status', 'path-age']) f.elements.set(id, new Element(id));
  const status = passiveFixture(), frame = { calibration_id: 'record', reference_id: 'origin', home: status.plan_home };
  const pose = { ...frame, x: 0, y: 0, theta: 0, observed_at: status.plan_observed_at, data_ready: true, navigation_ready: true };
  const map = { ...frame, width_cells: 2, height_cells: 1, grid: [0, 0], resolution_m: 1, origin_x: 0, origin_y: 0, observed_at: status.plan_observed_at, data_ready: true, planning_ready: true, navigation_ready: false };
  f.setReply('/api/navigator/status', { ...status, navigation: { pose, map, path: null } });
  const { Navigation } = await f.load('navigation.js'); const navigation = new Navigation(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(navigation.path.observed_at, status.plan_observed_at);
  assert.ok(f.elements.get('nav-goal').textContent.includes('HOME: (1, 0)'));
  assert.ok(f.elements.get('nav-goal').textContent.includes('plan tylko do odczytu'));
  assert.ok(f.elements.get('path-age').textContent.includes('fizycznie niezweryfikowany'));
  assert.ok(f.calls.every(call => call.method === 'GET'));
  assert.ok(f.elements.get('nav-status').textContent.startsWith('path_blocked'));
  const newer = { ...pose, reference_id: 'new', home: { ...pose.home, reference_id: 'new' } };
  navigation.event({ topic: 'robot.pose', data: newer });
  assert.ok(f.elements.get('nav-goal').textContent.includes('niepotwierdzony'));
  f.setReply('/api/navigator/status', { offline: true, navigator: status, navigation: { pose, map, path: null } });
  await navigation.poller.refresh();
  assert.equal(navigation.path.observed_at, null);
  assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('fresh passive domain refusal is observed state, while outer proxy failure cannot confirm it', async () => {
  const f = await fixture(), status = { ...passiveFixture(), generation: 'g', request_id: 'r' };
  const { Navigation } = await f.load('navigation.js'); const navigation = new Navigation(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  const entry = { generation: 'g', request_id: 'r', ts: status.observed_at - .1, status: 'pending' };
  navigation.history = [entry];
  for (const failure of [{ offline: true }, { stale: true }, { error: 'proxy lost' }, { data_error: 'proxy invalid' }]) {
    navigation.observeRequest(status, failure); assert.equal(entry.status, 'pending');
  }
  navigation.observeRequest(status, status);
  assert.equal(entry.status, 'task_observed'); assert.equal(entry.active, false);
  assert.equal(entry.error, 'navigation_traversal_unverified');
  assert.notEqual(entry.status, 'executed'); assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('navigation and system never append additional ARM forms', async () => {
  const navigationCard = new Element();
  const navigation = await fixture(disarmed(), { page: 'navigation', safetyCard: navigationCard });
  assert.equal(navigationCard.children.length, 0, 'passive navigation cannot append motion consent controls');
  assert.ok(navigation.calls.every(call => call.method === 'GET'));
  const systemCard = new Element();
  const system = await fixture(disarmed(), { page: 'system', safetyCard: systemCard });
  const nodes = value => [value, ...(value.children || []).flatMap(nodes)];
  assert.equal(nodes(systemCard).some(node => node.id === 'arm-form'), false);
  assert.ok(system.calls.every(call => call.method === 'GET'));
});

test('a passive plan is current only while both same-frame source observations remain usable', () => {
  const now = Date.now() / 1000, status = passiveFixture(now), plan = model.passivePlanObservation(status, null, now);
  const frame = { calibration_id: 'record', reference_id: 'origin', home: status.plan_home, observed_at: now - .2, data_ready: true };
  const pose = { ...frame, x: 0, y: 0, theta: 0, navigation_ready: true }, map = { ...frame, width_cells: 2, height_cells: 1, grid: [0, 0], resolution_m: 1, origin_x: 0, origin_y: 0, planning_ready: true, navigation_ready: false };
  assert.equal(model.passivePlanCurrent(plan, map, pose, now), true, 'map physical navigation flag stays false');
  for (const failure of [{ stale: true }, { offline: true }, { error: 'lost' }, { data_ready: false }, { data_ready: null },
    { data_error: 'invalid' }, { quality: 'unknown' }, { observed_at: now - 4 }]) {
    assert.equal(model.passivePlanCurrent(plan, { ...map, ...failure }, pose, now), false, JSON.stringify(failure));
    assert.equal(model.passivePlanCurrent(plan, map, { ...pose, ...failure }, now), false, JSON.stringify(failure));
  }
  assert.equal(model.passivePlanCurrent(plan, map, { ...pose, observed_at: now - .6 }, now), false);
  for (const invalid of [{ x: null }, { y: NaN }, { theta: undefined }]) assert.equal(model.passivePlanCurrent(plan, map, { ...pose, ...invalid }, now), false);
  for (const invalid of [{ grid: [] }, { grid: [0, NaN] }, { width_cells: 65537 }, { resolution_m: 0 }]) assert.equal(model.passivePlanCurrent(plan, { ...map, ...invalid }, pose, now), false);
  const truncated = model.passivePlanObservation({ ...status, planned_path_length: 150, planned_path_truncated: true }, null, now);
  assert.equal(truncated.path_length, 150); assert.equal(truncated.path_truncated, true);
});

test('point-plan rendering expires at the pose age budget without a new timestamp', async () => {
  const clock = { now: 1000 }, f = await fixture(disarmed(1000), { clock }), strokes = [];
  const context = { globalAlpha: 1, fillStyle: '', fillRect() {}, save() {}, restore() {}, translate() {}, rotate() {},
    beginPath() {}, moveTo() {}, lineTo() {}, stroke() { strokes.push(this.globalAlpha); }, arc() {}, fill() {} };
  const canvas = new Element('map-canvas'); canvas.clientWidth = 600; canvas.getContext = () => context; f.elements.set('map-canvas', canvas);
  const status = passiveFixture(1000), frame = { calibration_id: 'record', reference_id: 'origin', home: status.plan_home, observed_at: 999.8, data_ready: true };
  const pose = { ...frame, x: 0, y: 0, theta: 0, navigation_ready: true };
  const map = { ...frame, width_cells: 2, height_cells: 1, grid: [0, 0], resolution_m: 1, origin_x: 0, origin_y: 0, planning_ready: true, navigation_ready: false };
  f.setReply('/api/navigator/status', { ...status, navigation: { pose, map, path: null } });
  const { Navigation } = await f.load('navigation.js'); const navigation = new Navigation(f.panel);
  await new Promise(resolve => setImmediate(resolve));
  const key = navigation.drawKey; assert.ok(strokes.includes(1));
  clock.now += .4; navigation.render();
  assert.notEqual(navigation.drawKey, key); assert.equal(strokes.at(-1), .35);
  assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('passive pages never bind or dispatch motion shortcuts or a blur STOP', async () => {
  const f = await fixture(armed(), { interactive: false });
  assert.equal(f.panel.can('manual'), false);
  assert.equal(f.listeners.keydown, undefined);
  f.panel.key({ code: 'Space', target: new Element(), preventDefault() { throw new Error('passive shortcut captured'); } });
  f.panel.suspend();
  assert.ok(f.calls.every(call => call.method === 'GET'));
});
test('opening a panel with ESTOP never clears or arms automatically', async () => {
  const f = await fixture({ ...disarmed(), state: 'ESTOP' });
  f.panel.render();
  assert.equal(f.elements.get('global-motion-toggle').textContent, 'Robot rozbrojony');
  assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('another presentation clock cannot invalidate the safety permission clock', async () => {
  const f = await fixture(armed());
  assert.equal(f.panel.can('manual'), true);
  const clock = await f.load('model.js'), now = Date.now() / 1000;
  clock.setServerClock(now - 100, now, now);
  assert.equal(f.panel.can('manual'), true);
});
test('service inspection does not grant movement before administration is enabled', async () => {
  const f = await fixture(armed());
  f.document.body.dataset.page = 'system';
  assert.equal(f.panel.can('manual'), false);
  f.panel.key({ code: 'Space', target: new Element(), preventDefault() { throw new Error('read-only admin captured'); } });
  f.panel.suspend();
  assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('catalogue preflight completes before a 500 ms clear-estop envelope is created', async () => {
  const clock = { now: 1000 };
  const f = await fixture({ ...disarmed(1000), state: 'ESTOP' }, { clock, catalogDelay: .7 });
  f.elements.get('operator-plan').value = 'Isolated fixture';
  f.elements.get('operator-consent').checked = true;
  await assert.rejects(f.panel.toggleMotion(), /rozbrojenia/);
  const write = f.calls.find(call => call.method === 'POST');
  assert.ok(write);
  assert.equal(write.body.ts, clock.now);
  assert.equal(write.body.ttl_ms, 500);
  const paths = f.calls.map(call => call.url);
  assert.ok(paths.indexOf('/api/logic/catalog') < paths.indexOf('/api/safety'));
});

test('one global toggle arms explicitly without a plan form or owner options', async () => {
  const f = await fixture(disarmed(), { page: 'view', interactive: false });
  const button = f.elements.get('global-motion-toggle');
  assert.equal(button.textContent, 'Robot rozbrojony');
  assert.equal(button.disabled, false);
  assert.ok(f.calls.every(call => call.method === 'GET'));
  await f.panel.toggleMotion();
  const writes = f.calls.filter(call => call.method === 'POST');
  assert.equal(writes.length, 1);
  assert.equal(writes[0].body.action, 'arm');
  assert.equal(writes[0].body.owner, 'manual');
  assert.equal(writes[0].body.operator_consent, true);
  assert.equal(writes[0].body.execution_context, 'panel');
  assert.equal(writes[0].body.arming_mode, 'operator');
  assert.equal(writes[0].body.lease_s, undefined);
  assert.equal(writes[0].body.test_operator_consent, undefined);
  assert.equal(button.textContent, 'Robot rozbrojony', 'HTTP acceptance never turns button green');
  f.setState(armed());
  assert.equal(button.textContent, 'Robot uzbrojony');
  assert.equal(button['aria-pressed'], 'true');
});

test('global toggle clears and arms in one click only after fresh confirmed clearing', async () => {
  const f = await fixture({ ...disarmed(), state: 'ESTOP' }), calls = [];
  f.panel.send = async action => {
    calls.push(action);
    if (action === 'clear_estop') f.setState({ ...disarmed(), generation: 'new-clear' });
  };
  await f.panel.toggleMotion();
  assert.deepEqual(calls, ['clear_estop', 'arm']);
  const blocked = await fixture({ ...disarmed(), state: 'ESTOP' }), attempts = [];
  blocked.panel.send = async action => { attempts.push(action); };
  await assert.rejects(blocked.panel.toggleMotion(), /rozbrojenia/);
  assert.deepEqual(attempts, ['clear_estop']);
});

test('global disarm stays available with stale state and does not need consent', async () => {
  const f = await fixture(armed());
  f.panel.clockReady = false; f.panel.render();
  assert.equal(f.elements.get('global-motion-toggle').disabled, false);
  await f.panel.toggleMotion();
  assert.equal(f.calls.filter(call => call.method === 'POST').at(-1).body.action, 'stop');
});

test('test lease never enables panel direction controls', async () => {
  const f = await fixture({ ...armed(), execution_context: 'test', panel_motion_enabled: false, test_motion_enabled: true });
  assert.equal(f.panel.can('manual'), false);
  f.panel.move('forward');
  assert.ok(f.calls.every(call => call.method === 'GET'));
});

test('operator arming survives thirty seconds and focus suspension without auto STOP', async () => {
  const f = await fixture({ ...armed(), execution_context: 'panel', arming_mode: 'operator', lease_remaining_s: null });
  assert.equal(f.panel.can('manual'), true);
  f.panel.suspend();
  assert.ok(f.calls.every(call => call.method === 'GET'));
  f.setState({ ...armed(), execution_context: 'panel', arming_mode: 'operator', lease_remaining_s: null });
  assert.equal(f.panel.can('manual'), true);
  assert.equal(f.elements.get('global-motion-toggle').textContent, 'Robot uzbrojony');
});

test('release creates its fresh envelope after slow catalogue negotiation',async()=>{
  const clock={now:1000};
  const f=await fixture(armed(1000),{clock,catalogDelay:.7});
  f.panel.controls={state:{revision:17},ready:()=>true,pulse:direction=>({direction,device_settings:true,settings_revision:17})};
  await f.panel.sendIntent({direction:'forward',mode:'release'},()=>true);
  const write=f.calls.find(call=>call.method==='POST').body;
  assert.equal(write.ts,clock.now);
  assert.equal(write.mode,'release');assert.equal(write.ttl_ms,500);assert.equal(write.seq,5);
});
test('release can neutralize a held gesture after a lost state without renewing old commands',async()=>{
  const clock={now:1000};let f;
  f=await fixture(armed(1000),{clock,catalogDelay:.7,
    beforeFetch:async url=>{if(url==='/api/logic/catalog')f.setState(null);}});
  f.panel.controls={state:{revision:17},ready:()=>true,pulse:direction=>({direction,device_settings:true,settings_revision:17})};
  await f.panel.sendIntent({direction:'forward',mode:'release'},()=>true);
  const write=f.calls.find(call=>call.method==='POST').body;
  assert.equal(write.ts,clock.now);assert.equal(write.generation,'fixture-generation');
  assert.equal(write.mode,'release');assert.equal(write.ttl_ms,500);assert.equal(write.seq,5);
});


test('operator ARM remains visible and directions available after observation expiry', async () => {
  const state = { ...armed(), arming_mode: 'operator', execution_context: 'panel', lease_remaining_s: null };
  const f = await fixture(state);
  f.panel.clockObserved -= 10;
  f.setState({ ...state, stale: true, ready: false, can_move: false, observed_at: state.observed_at - 10 });
  assert.equal(f.panel.can(), true);
  assert.match(f.elements.get('global-motion-toggle').textContent, /^Robot uzbrojony/);
  assert.doesNotMatch(f.elements.get('global-motion-toggle').textContent, /rozbrojony/);
  await f.panel.send('move', { vx: .1, yaw: 0, duration: .1 });
  assert.equal(f.calls.filter(call => call.method === 'POST').at(-1).body.action, 'move');
});

test('missing observation retains permission, explicit disarm replaces it', async () => {
  const f = await fixture({ ...armed(), arming_mode: 'operator', execution_context: 'panel' });
  f.panel.update({ state: 'UNKNOWN', stale: true });
  assert.equal(f.panel.can(), true);
  assert.match(f.elements.get('global-motion-toggle').textContent, /^Robot uzbrojony/);
  f.panel.update(disarmed());
  assert.equal(f.panel.can(), false);
  assert.equal(f.elements.get('global-motion-toggle').textContent, 'Robot rozbrojony');
});
