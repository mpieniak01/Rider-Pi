import assert from 'node:assert/strict';
import test from 'node:test';
import {Node, environment, load, settle, transport} from './helpers/pr308-operator-fixture.mjs';

const translate = (key, params) => params?.message ? key + ':' + params.message : key;
const dictionary = {initI18n() {}, applyDom() {}, t: translate};
async function footer({version = {available: true, commit: 'abc1234', branch: 'HEAD'}, pending = [], templateError = false, themeApi = null} = {}) {
  const f = environment();
  const targets = [new Node('footer'), new Node('footer')];
  const keys = ['presence', 'presence-state', 'mode', 'conf', 'camera', 'camera-meta', 'theme-select', 'branch', 'commit', 'dirty'];
  for (const target of targets) {
    target.setAttribute('data-footer-root', '');
    for (const key of keys) {
      const child = new Node(key === 'commit' ? 'button' : 'span'); child.setAttribute('data-footer-' + key, '');
      child.textContent = key + ': —'; target.append(child);
    }
  }
  f.globals.document.querySelectorAll = selector => selector === '[data-dashboard-footer-target]' ? targets : [];
  f.globals.window.i18n = {};
  f.globals.window.__footerPending = pending;
  if (themeApi) f.globals.window.dashboardTheme = themeApi;
  f.globals.fetch = async (url, options) => {
    f.calls.push({url, options});
    if (url === '/web/dashboard_footer_template.html') return {ok: !templateError, status: templateError ? 503 : 200, text: async () => '<div data-footer-root>fixture</div>'};
    assert.equal(url, '/api/status/version');
    return {ok: version !== null, status: version === null ? 503 : 200, json: async () => version};
  };
  await load('footer.js', f, {'i18n.js': dictionary}); await settle();
  return {...f, targets, field: (name, index = 0) => targets[index].querySelector('[data-footer-' + name + ']')};
}

for (const [version, expected] of [
  [{available: true, commit: 'abc1234', branch: 'HEAD', message: 'fixture release', dirty: true},
    {branch: 'footer.detached', title: 'footer.last_commit:fixture release', disabled: false, hidden: false}],
  [{available: true, commit: 'abc1234', branch: 'feature'},
    {branch: 'feature', title: 'footer.copy', disabled: false, hidden: true}],
  [{available: true, commit: 'abc1234'}, {branch: '—', title: 'footer.copy', disabled: false, hidden: true}],
  [{available: true, commit: 'not-a-commit', branch: 'main'},
    {branch: 'footer.unavailable', title: 'footer.unavailable', disabled: true, hidden: true}],
  [null, {branch: 'footer.unavailable', title: 'footer.unavailable', disabled: true, hidden: true}],
]) test('footer startup renders version availability and branch precedence: ' + JSON.stringify(version), async () => {
  const f = await footer({version});
  assert.equal(f.field('branch').textContent, expected.branch);
  assert.equal(f.field('commit').disabled, expected.disabled);
  assert.equal(f.field('commit').title, expected.title);
  assert.equal(f.field('dirty').hidden, expected.hidden);
  assert.equal(f.calls.length, 2);
  assert.equal(f.calls[1].options.cache, 'no-store');
  assert.equal(f.jobs.size, 0);
  await f.emit('dashboard:langchange');
  assert.equal(f.field('branch', 1).textContent, expected.branch);
});

test('footer fallback template and HTTP clipboard fallback preserve cleanup and focus', async () => {
  const f = await footer({templateError: true});
  assert.match(f.targets[0].markup, /data-footer-theme-select/);
  const focused = new Node('input'); f.globals.document.activeElement = focused;
  f.globals.document.execCommand = command => { assert.equal(command, 'copy'); return true; };
  await f.field('commit').onclick();
  assert.equal(f.field('commit').textContent, 'footer.copied');
  assert.equal(focused.focused, true);
  assert.equal(f.body.children[0].removed, true);
  const timer = [...f.jobs.values()].find(job => job.ms === 1500);
  assert.ok(timer); timer.fn();
  assert.equal(f.field('commit').textContent, '#abc1234');
  f.globals.document.execCommand = () => false;
  await f.field('commit').onclick();
  assert.equal(f.field('commit').title, 'footer.copy_failed');
});

test('footer update bridge ignores inherited keys and renders current stale idle and camera-disabled evidence', async () => {
  const f = await footer({pending: [{state: {observed_at: 1000, present: true, mode: 'ssd', confidence: .5}}]});
  assert.equal(f.field('presence-state').textContent, 'ACTIVE');
  const update = f.globals.window.dashboardFooter.update;
  update(Object.create({state: {present: false}, cameraResource: {free: true}}));
  assert.equal(f.field('presence-state').textContent, 'ACTIVE');
  update({state: {observed_at: 1000, present: false, camera: {on: true, fps: 12}},
    snapInfo: {raw: {age_s: 1}, proc: {age_s: 86400}, tracker: {age_s: null}},
    cameraResource: {holders: [{cmd: 'capture', pid: 42, service: 'camera.service'}, null]}});
  assert.equal(f.field('presence-state').textContent, 'IDLE');
  assert.equal(f.field('camera').className, 'c-pill ok');
  assert.match(f.field('camera').textContent, /1.0s \/ 1d/);
  assert.match(f.field('camera-meta').textContent, /capture#42:camera.service/);
  assert.match(f.field('camera-meta').textContent, /proc#\?/);
  update({state: {observed_at: 990, present: true, camera: {vision_enabled: false}}, cameraResource: {error: 'busy'}});
  assert.equal(f.field('presence-state').textContent, '—');
  assert.equal(f.field('camera').textContent, 'camera: OFF');
  update({state: null, cameraResource: {free: true}});
  assert.equal(f.field('camera').className, 'c-pill off');
  assert.equal(f.field('camera-meta').textContent, 'camera-meta: free');
});

test('footer theme fallback changes dataset and synchronizes both selects without a theme API', async () => {
  const f = await footer();
  f.field('theme-select').value = 'v3'; await f.field('theme-select').fire('change');
  assert.equal(f.globals.document.documentElement.dataset.dashboardTheme, 'v3');
  assert.equal(f.field('theme-select', 1).value, 'v3');
  f.field('theme-select', 1).value = 'unknown'; await f.field('theme-select', 1).fire('change');
  assert.equal(f.globals.document.documentElement.dataset.dashboardTheme, 'classic');
  assert.equal(f.field('theme-select').value, 'classic');
});

async function application(page = 'control') {
  const f = environment(['actuator-capabilities', 'operator-message', 'last-event', 'chat-send'], page);
  const instances = new Map(), changes = [], stubs = {};
  const names = { 'camera-pipeline.js': ['CameraPipelineControls', 'PipelinePreview'], 'remote-navigation.js': ['RemoteNavigation'], 'navigation-profiles.js': ['NavigationProfiles'], 'model-tuning.js': ['ModelTuning'], 'perception-models.js': ['PerceptionModels'],
    'camera-power.js': ['CameraPower'], 'posture.js': ['Posture'], 'manual-settings.js': ['ManualSettings'],
    'control-camera.js': ['ControlCamera'], 'tasks.js': ['Tasks'], 'devices.js': ['Devices'], 'system.js': ['System'],
    'navigation.js': ['Navigation'], 'calibration.js': ['Calibration'], 'chat.js': ['Chat'], 'overview.js': ['Overview'] };
  for (const [file, exports] of Object.entries(names)) {
    stubs[file] = Object.fromEntries(exports.map(name => [name, class {
      constructor(...args) { this.args = args; this.renders = 0; this.poller = {stop: () => changes.push('stop:' + name)}; instances.set(name, this); }
      render() { this.renders++; } event(value) { this.lastEvent = value; } loadProviders() { changes.push('providers'); }
    }]));
  }
  class Safety {
    constructor(callback, options) { this.callback = callback; this.options = options; this.revokedGenerations = new Set(); instances.set('Safety', this); }
    clockFresh() { return true; } can() { return false; }
    render() { this.callback(this.state); }
    update(state) { this.state = state; this.render(); }
    ack(value) { this.lastAck = value; }
  }
  stubs['safety.js'] = {SafetyPanel: Safety};
  stubs['i18n.js'] = {initI18n() {}};
  stubs['transport.js'] = {events: (receive, failed) => { f.receive = receive; f.failed = failed; }};
  await load('operator/app.js', f, stubs);
  return {...f, instances, changes};
}

test('full operator bootstrap presents mixed capabilities and refreshes stale evidence without granting authority', async () => {
  const f = await application(), safety = f.instances.get('Safety');
  const state = {contract_version: 1, state: 'ARMED', generation: 'g', observed_at: 1000, can_move: true,
    ready: true, hardware_ready: true, capabilities: {
      move: {available: true, stop_verified: true}, turn: {available: true, verification: 'manual_characterization_required'},
      height: {available: true}, balance: {available: false},
    }};
  safety.update(state);
  assert.deepEqual(f.node('actuator-capabilities').children.map(node => node.textContent), [
    'move: available after arming', 'turn: blocked — manual characterization and interruption required',
    'balance: unavailable / unverified', 'height: available after arming', 'action: unavailable / unverified',
  ]);
  safety.update({...state, observed_at: 990});
  assert.ok(f.node('actuator-capabilities').children.every(node => node.textContent.endsWith('unavailable / unverified')));
  assert.equal(f.instances.get('Safety').options.interactive, true);
  assert.equal(f.calls.length, 0);
  await f.emit('pagehide', {persisted: true}); assert.deepEqual(f.changes, []);
  await f.emit('pagehide', {persisted: false}); assert.deepEqual(f.changes, ['stop:ControlCamera']);
});

test('navigation bootstrap routes acknowledgements, malformed event data and stream failures safely', async () => {
  const f = await application('navigation'), nav = f.instances.get('Navigation');
  assert.ok(f.instances.has('ModelTuning'));
  f.receive({topic: 'motion.state', data: '{bad'});
  assert.equal(nav.lastEvent.data, '{bad');
  f.receive({topic: 'motion.ack', data: '{"status":"rejected"}', ts: 7});
  assert.equal(f.instances.get('Safety').lastAck.status, 'rejected');
  assert.equal(f.node('last-event').textContent, 'motion.ack · 7');
  f.failed(); assert.match(f.node('last-event').textContent, /periodic reads active/);
  assert.equal(f.instances.get('Safety').options.interactive, false);
  assert.equal(f.calls.length, 0);
});

const deviceIds = ['camera-image', 'preview-kind', 'preview-url', 'device-list', 'telemetry-list', 'preview-toggle',
  'preview-refresh', 'preview-url-form', 'camera-preview-state', 'camera-age', 'camera-display-age', 'operator-message'];
async function devices(reply) {
  const f = environment(deviceIds); f.node('preview-kind').value = 'raw';
  const boundary = transport(f, reply);
  const module = await load('operator/devices.js', f, {
    'transport.js': boundary.exports, 'camera-power.js': {CameraPower: class {constructor(options) { this.options = options; }}},
  });
  return {...f, boundary, panel: new module.Devices()};
}

test('device inventory distinguishes on off and unknown power without deriving movement permission', async () => {
  const f = await devices(async path => {
    if (path.includes('snap-info')) return {data: {}};
    if (path.endsWith('speaker')) throw new Error('inventory unavailable');
    let on = null;
    if (path.endsWith('camera')) on = true;
    else if (path.endsWith('lcd')) on = false;
    return {data: {observed_at: 1000, state: 'free', activity: {on}, holders: []}};
  });
  await f.panel.load();
  const cards = f.node('device-list').children;
  assert.equal(cards.length, 5);
  assert.match(cards[0].textContent, /ON/);
  assert.match(cards[3].textContent, /OFF/);
  assert.match(cards[2].textContent, /inventory unavailable/);
  assert.equal(f.panel.preview, false);
  assert.ok(f.calls.every(call => call.method === undefined));
  await f.emit('pagehide');
  assert.ok(f.boundary.pollers.every(poller => poller.stopped));
});

for (const [readyCount, expectedLabel] of [[0, /IMU: missing \/ stale data/], [1, /IMU: partial reading/], [3, /IMU: fresh transport/]]) test('device telemetry keeps partial/stale raw values separate from ready measurements: ' + readyCount, async () => {
  const sensors = Object.fromEntries(['roll', 'pitch', 'yaw'].map((name, index) => [name,
    {value: index + 1, unit: 'sdk_raw', observed_at: 1000, ready: index < readyCount}]));
  sensors.battery = {value: .5, unit: 'ratio', observed_at: 995, ready: true};
  const xgo = {contract_id: 'rider.telemetry', contract_version: 1, source: 'fixture', sensor_quality: {sensors}};
  const f = await devices(async () => ({data: {devices: {xgo}}}));
  await f.panel.loadTelemetry();
  const text = f.node('telemetry-list').textContent;
  assert.match(text, expectedLabel);
  assert.match(text, /50% · unconfirmed \/ stale/);
  assert.match(text, /wrapping does not correct the sensor/);
  sensors.roll.value = 'invalid'; sensors.pitch.value = Number.NaN;
  f.panel.renderTelemetry();
  const fields = f.node('telemetry-list').querySelector('dl').children;
  const values = new Map(Array.from({length: fields.length / 2}, (_, i) => [fields[i * 2].textContent, fields[i * 2 + 1].textContent]));
  assert.equal(values.get('roll (raw SDK)'), '— · unconfirmed / stale');
  assert.equal(values.get('pitch (raw SDK)'), '— · unconfirmed / stale');
  assert.equal(f.calls.length, 1);
});

test('device preview reports unknown and file ages and rejects off-origin snapshots before image mutation', async () => {
  const f = await devices();
  f.panel.renderPreview(); assert.match(f.node('camera-age').textContent, /unknown/);
  f.panel.meta = {raw: {exists: true, observed_at: null, provenance: 'file_mtime', file_observed_at: 998}};
  f.panel.renderPreview();
  assert.match(f.node('camera-age').textContent, /file age 2.0 s/);
  assert.match(f.node('camera-age').textContent, /capture time unconfirmed/);
  f.panel.preview = true;
  f.node('preview-url').value = 'https://outside.invalid/vision/cam';
  f.panel.frame();
  assert.equal(f.node('camera-image').src, undefined);
  assert.equal(f.panel.imageBusy, false);
  assert.match(f.node('operator-message').textContent, /local camera snapshot/);
  f.node('preview-url').value = '/vision/cam'; f.panel.frame();
  assert.match(f.node('camera-image').src, /^http:\/\/fixture.invalid\/vision\/cam\?t=998$/);
  assert.equal(f.panel.imageBusy, true);
  const timeout = [...f.jobs.values()].find(job => job.ms === 6000); assert.ok(timeout); timeout.fn();
  assert.equal(f.panel.imageBusy, false);
  assert.equal(f.node('camera-image').hidden, true);
  assert.match(f.node('camera-display-age').textContent, /no confirmed frame/);
  assert.equal(f.calls.length, 0);
});

function postureTree(f) {
  const root = f.node('posture-controls');
  for (const name of ['height', 'balance', 'action', 'height-send', 'balance-send', 'action-send', 'state', 'action-status']) {
    const node = new Node(name.endsWith('send') ? 'button' : 'input'); root.routes.set('#posture-' + name, node);
  }
  root.routes.set('output', new Node('output')); return root;
}
for (const [balance, label] of [[true, 'on'], [false, 'off'], [undefined, '—']]) test('posture renders strictly observed balance state without sending: ' + label, async () => {
  const f = environment(['posture-controls', 'operator-message'], 'control'), root = postureTree(f), sends = [];
  const safety = {state: {actuators: {height: {value: 90}, balance: {enabled: balance}}}, can: () => false,
    send: (...args) => sends.push(args)};
  const module = await load('operator/posture.js', f), panel = new module.Posture(safety);
  assert.match(root.querySelector('#posture-state').textContent, new RegExp('balance ' + label));
  assert.equal(root.querySelector('#posture-balance-send').disabled, true);
  await panel.send('balance', {enabled: true});
  assert.equal(sends.length, 0);
  assert.equal(f.calls.length, 0);
});

test('optional TTS discovery failure retains text chat and missing/moving domains never start', async () => {
  const f = environment(['chat-form', 'chat-provider', 'chat-status', 'chat-board', 'operator-message']);
  const boundary = transport(f, async () => { throw new Error('TTS catalog failure'); });
  const module = await load('operator/chat.js', f, {'transport.js': boundary.exports});
  const tasks = {catalog: {contract_version: 2, catalog_version: 2, api_envelope_versions: [1], observed_at: 1000, features: [], units: []},
    options: new Map(), safety: {state: {}}, poller: {refresh() { assert.fail('Rejected domain must not refresh'); }}};
  const chat = new module.Chat(tasks); await chat.loadProviders();
  assert.match(f.node('chat-status').textContent, /text chat requires its prepared domain/);
  assert.equal(chat.busy, false);
  await assert.rejects(chat.prepareDomain('provider', 'text'), /Domain unavailable/);
  const domain = {name: 'provider', option_kind: 'provider', can_move: true,
    option_schema: {choices: [{value: 'text'}]}, requested: true, options: {domain: 'text'},
    ready: true, observed_at: 1000};
  tasks.catalog.features.push(domain);
  await assert.rejects(chat.prepareDomain('provider', 'text'), /Domain unavailable/);
  domain.can_move = false;
  await chat.prepareDomain('provider', 'text');
  assert.equal(tasks.options.size, 0);
  assert.deepEqual(f.calls.map(call => call.path), ['/api/voice/providers']);
});

for (const [status, expected] of [
  [{stale: true, running: true}, 'Loop state unknown or stale.'],
  [{running: true, decision: {state: 'pending'}, stop_reason: 'operator'}, 'running · pending · operator'],
  [{running: false}, 'stopped · unknown · '],
]) test('remote load reports stale/running/stopped observations without starting a feature: ' + expected, async () => {
  const ids = ['remote-load', 'remote-save', 'remote-arm', 'remote-observe', 'remote-drive', 'remote-stop',
    'remote-mode', 'remote-speed', 'remote-decision_budget_ms', 'remote-max_motion_ms', 'remote-calibration_id',
    'remote-model_sha256', 'remote-corridor', 'remote-verified', 'remote-state'];
  const f = environment(ids, 'navigation');
  const boundary = transport(f, async path => ({data: path.endsWith('config') ? {mode: 'observe', corridor: [0, 1], verified: false} : status}));
  const module = await load('operator/remote-navigation.js', f, {'transport.js': boundary.exports});
  const panel = new module.RemoteNavigation({send() { assert.fail('Observation must not send control'); }});
  await panel.load();
  assert.equal(f.node('remote-state').textContent, expected);
  assert.equal(f.node('remote-verified').checked, false);
  assert.ok(f.calls.every(call => call.method === undefined));
});

async function safetyFixture() {
  const f = environment(['global-motion-toggle', 'operator-message', 'request-history', 'safety-state', 'safety-reason', 'speed', 'yaw-speed', 'duration'], 'control');
  let panel;
  const boundary = transport(f, async (path, options) => {
    if (path === '/api/control/state') return {canonical: true, meta: {contract_id: 'rider.safety', contract_version: 1},
      data: {server_time: 1000, safety: panel.state}, sent_at: 1000, received_at: 1000};
    options.beforeSend?.(); return {data: {ack: {status: 'executed'}}};
  });
  const module = await load('operator/safety.js', f, {'transport.js': boundary.exports,
    'held-motion.js': {HeldMotion: class {stop() {} end() {}}}, 'request-id.js': {requestId: () => 'pr308-memory-intent'}});
  panel = new module.SafetyPanel();
  panel.clockReady = true; panel.clockObserved = 1000;
  panel.controls = {commandReady: () => true, state: {revision: 'r'}, pulse: () => ({vx: 0, yaw: 0, duration: .1})};
  panel.update({contract_version: 1, state: 'ARMED', generation: 'g', owner: 'manual', observed_at: 1000,
    ready: true, hardware_ready: true, can_move: true, read_only: false, lease_remaining_s: 10,
    capabilities: {move: {available: true, stop_verified: true}}});
  return {...f, panel, boundary};
}
for (const [mode, label] of [['release', 'Decelerating; robot remains armed.'], ['hold', 'Held — continuous command.'], ['pulse', 'Pulse sent.']])
  test('fake accepted intent feedback remains distinct for ' + mode, async () => {
    const f = await safetyFixture();
    await f.panel.sendIntent({mode, direction: 'forward'}, () => true);
    assert.equal(f.node('operator-message').textContent, label);
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].path, '/api/control');
    assert.equal(f.calls[0].body.mode, mode);
    assert.equal(f.calls[0].body.vx, 0);
  });

test('revoked safety or invalidated intent never reaches even the fake control boundary', async () => {
  const f = await safetyFixture(), originalSequence = f.panel.seq; f.panel.revoke(); f.panel.render();
  assert.match(f.node('safety-reason').textContent, /locally revoked/);
  await assert.rejects(f.panel.sendIntent({mode: 'hold', direction: 'forward'}, () => true), /cancelled_or_stale/);
  assert.equal(f.calls.length, 0);
  assert.equal(f.panel.seq, originalSequence);
  f.panel.revokedGenerations.clear();
  await assert.rejects(f.panel.sendIntent({mode: 'hold', direction: 'forward'}, () => false), /cancelled_or_stale/);
  assert.equal(f.calls.length, 0);
});



test('blank legacy movement fields reject before a control POST and release mutation ownership', async () => {
  const f = await safetyFixture(); f.panel.controls = null;
  f.node('duration').value = '';
  f.panel.move('forward'); await settle();
  assert.match(f.node('operator-message').textContent, /Invalid pulse/);
  assert.equal(f.panel.mutating, false);
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
  assert.equal(f.calls.length, 0);
});

test('request history distinguishes rejected reasons from accepted SDK commands and physical completion', async () => {
  const f = await safetyFixture();
  f.panel.history = [
    {submittedAt: 1000, command: {action: 'move'}, status: 'rejected', reason: 'revoked'},
    {submittedAt: 1000, command: {action: 'stop'}, status: 'executed', ack: {status: 'executed'}},
  ];
  f.panel.renderHistory();
  const rows = f.node('request-history').children;
  assert.match(rows[0].textContent, /Rejected · revoked/);
  assert.doesNotMatch(rows[0].textContent, /physical completion/);
  assert.match(rows[1].textContent, /SDK accepted · physical completion unverified/);
  assert.equal(f.calls.length, 0);
});
