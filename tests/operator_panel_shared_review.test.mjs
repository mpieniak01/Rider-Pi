// Isolated source modules and DOM fixtures: no network, timers or robot SDK.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const assets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../web/assets/operator');
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {};
    this.className = ''; this.nodeType = 1; this.open = false; this.value = ''; this.checked = false;
    this.classes = new Set();
    this.classList = { add: name => this.classes.add(name), toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name) };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll(selector) {
    const result = [];
    for (const child of this.children) {
      if (!(child instanceof Element)) continue;
      if ((selector === 'details[data-system-detail]' && child.tagName === 'details' && Object.hasOwn(child.dataset, 'systemDetail'))
        || (selector === '.operator-age' && child.className.split(' ').includes('operator-age'))
        || (selector === '[data-status-max-age]' && Object.hasOwn(child.dataset, 'statusMaxAge'))) result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
}
async function fixture() {
  let clock = 1000;
  const calls = [], replies = new Map(), elements = new Map();
  const body = new Element('body');
  for (const id of ['service-list', 'system-details-data', 'rescue-release', 'rescue-resource']) {
    const node = new Element(); elements.set(id, node); body.append(node);
  }
  const document = { hidden: false, documentElement: { lang: 'en' }, body,
    createElement: tag => new Element(tag), getElementById: id => elements.get(id),
    querySelectorAll: selector => body.querySelectorAll(selector), addEventListener() {}, removeEventListener() {} };
  const context = vm.createContext({ document, window: { addEventListener() {} }, console,
    Date: class extends Date { static now() { return clock * 1000; } }, AbortController,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    fetch: async (url, options) => {
      assert.equal(options.method, 'GET', 'presentation must never mutate the robot'); calls.push(url);
      const reply = replies.get(url) || {};
      return { ok: true, status: 200, headers: { get: name => name.toLowerCase() === 'content-type'
        ? (reply.meta ? 'application/vnd.rider.api+json;version=1' : 'application/json') : null }, json: async () => reply };
    } });
  const modules = new Map();
  function load(name) {
    if (!modules.has(name)) modules.set(name, readFile(path.join(assets, name), 'utf8').then(source =>
      new vm.SourceTextModule(source, { context, identifier: name })));
    return modules.get(name);
  }
  return { document, elements, calls, replies, advance: seconds => { clock += seconds; },
    async load(name) {
      const module = await load(name);
      if (module.status === 'unlinked') await module.link(specifier => load(path.basename(specifier).split('?')[0]));
      if (module.status === 'linked') await module.evaluate();
      return module.namespace;
    } };

}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('active RAW capture does not label inactive derivative preview producers as enabled', async () => {
  const f = await fixture();
  const { Overview } = await f.load('overview.js');
  for (const id of ['d_cam', 'camBadge', 'age_raw', 'age_proc', 'age_obst', 'age_tracker']) f.elements.set(id, new Element());
  for (const name of ['cam', 'proc', 'obst', 'tracker']) {
    f.elements.set(`leg_${name}_txt`, new Element());
    const image = new Element('img');
    image.getAttribute = key => image[key];
    f.elements.set(`img_${name}`, image);
  }
  const file = (exists, at) => ({ exists, observed_at: null, capture_at: null,
    file_observed_at: at, provenance: 'file_mtime', stale: exists && at < 997, max_age_s: 3 });
  const overview = { health: { devices: { camera: { on: true } } }, state: { camera: { mode: 'raw', fps: 12 } },
    snap: { raw: file(true, 999.8), proc: file(false, null), obst: file(false, null), tracker: file(true, 900) },
    obstacle: null, drawBins() {} };
  for (const lang of ['pl', 'en']) {
    f.document.documentElement.lang = lang;
    Overview.prototype.renderVision.call(overview);
    assert.ok(f.elements.get('d_cam').textContent.startsWith('ON'));
    assert.equal(f.elements.get('camBadge').textContent, 'ON');
    for (const [name, kind] of [['cam', 'RAW'], ['proc', 'PROC'], ['obst', 'OBST'], ['tracker', 'TRACKER']]) {
      const label = f.elements.get(`leg_${name}_txt`).textContent;
      assert.ok(label.startsWith(`${kind} · `));
      assert.doesNotMatch(label, /ON|OFF/);
    }
    assert.ok(f.elements.get('leg_proc_txt').textContent.includes(lang === 'pl' ? 'brak klatki' : 'no frame'));
    assert.ok(f.elements.get('leg_obst_txt').textContent.includes(lang === 'pl' ? 'brak klatki' : 'no frame'));
    assert.ok(f.elements.get('leg_tracker_txt').textContent.includes(lang === 'pl' ? 'stara klatka' : 'old frame'));
    assert.ok(f.elements.get('leg_cam_txt').textContent.includes(lang === 'pl' ? 'wiek pliku' : 'file age'));
    assert.ok(f.elements.get('img_cam').src.startsWith('/vision/cam?v='));
    for (const name of ['proc', 'obst', 'tracker']) assert.ok(f.elements.get(`img_${name}`).src.startsWith('data:image/svg+xml,'));
  }
  assert.equal(f.calls.length, 0, 'rendering never starts or queries a producer');
});

test('LCD control events retain ON/OFF with original confirmation age beyond ten seconds', async () => {
  const f = await fixture(); const { Overview } = await f.load('overview.js');
  f.elements.set('d_lcd', new Element());
  const lcd = { source: 'lcd-renderer', power_source: 'lcd-renderer', power_known: true,
    confirmation: 'control_write_accepted', power_observed_at: 1000, observed_at: 1000,
    physical_validity: 'unverified', rot: 270 };
  const overview = { state: null, health: { devices: { lcd } } };
  for (const lang of ['pl', 'en']) {
    f.document.documentElement.lang = lang;
    for (const on of [false, true]) {
      lcd.on = on;
      Overview.prototype.renderTelemetry.call(overview);
      const label = f.elements.get('d_lcd').textContent;
      assert.equal(label, on ? 'ON' : 'OFF');
      assert.ok(f.elements.get('d_lcd').title.includes(lang === 'pl' ? 'Ostatnie' : 'Last'));
    }
  }
  f.advance(11);
  Overview.prototype.renderTelemetry.call(overview);
  assert.equal(f.elements.get('d_lcd').textContent, 'ON');
  assert.equal(lcd.power_observed_at, 1000, 'rendering never refreshes the original confirmation time');
  lcd.on = false;
  f.advance(45);
  Overview.prototype.renderTelemetry.call(overview);
  assert.equal(f.elements.get('d_lcd').textContent, 'OFF');
  assert.equal(f.calls.length, 0, 'event presentation makes no API or GPIO request');
});

test('LCD labels are unknown without explicit power proof or with transport failure', async () => {
  const f = await fixture(); const { Overview } = await f.load('overview.js');
  f.elements.set('d_lcd', new Element());
  const lcd = { source: 'lcd-renderer', power_source: 'lcd-renderer', power_known: true, on: false,
    confirmation: 'control_write_accepted', power_observed_at: 990, observed_at: 1000 };
  for (const change of [{ power_known: false }, { power_known: undefined }, { on: null }, { source: '' },
    { source: null }, { power_source: 'camera-preview' }, { confirmation: 'frame_write_accepted' },
    { power_observed_at: null, ts: 1000 }, { power_observed_at: 1001 }, { power_observed_at: 1000.01 }, { offline: true },
    { stale: true }, { error: 'source_failed' }, { simulated: true }]) {
    Overview.prototype.renderTelemetry.call({ state: null, health: { devices: { lcd: { ...lcd, ...change } } } });
    assert.equal(f.elements.get('d_lcd').textContent, 'Unknown', JSON.stringify(change));
  }
  for (const failure of [{ offline: true }, { stale: true }, { error: 'API unavailable' },
    { meta: { offline: true } }, { meta: { stale: true } }, { meta: { error: 'proxy failed' } }]) {
    Overview.prototype.renderTelemetry.call({ state: null, health: { devices: { lcd }, ...failure } });
    assert.equal(f.elements.get('d_lcd').textContent, 'Unknown', JSON.stringify(failure));
  }
  Overview.prototype.renderTelemetry.call({ state: { devices: { lcd }, offline: true }, health: { devices: { lcd } } });
  assert.equal(f.elements.get('d_lcd').textContent, 'Unknown', 'explicit failing selected parent cannot use healthy fallback');
});

test('explicit unknown observation never becomes fresh through age refresh or legacy ts', async () => {
  const f = await fixture(); const ui = await f.load('ui.js');
  for (const observed_at of [null, undefined, NaN, Infinity, 0]) {
    const row = { observed_at, ts: 1000 };
    const stamp = ui.ageStamp(row), status = ui.freshPill(row, 'active', 'ok');
    f.document.body.append(stamp, status);
    assert.equal(stamp.textContent, 'age unknown'); assert.equal(status.textContent, 'unknown / stale');
    f.advance(.1); ui.refreshAges();
    assert.equal(stamp.textContent, 'age unknown'); assert.equal(status.textContent, 'unknown / stale');
    assert.equal(stamp.classes.has('operator-error'), true);
  }
});
test('legacy ts remains valid only when observed_at is absent, then ages conservatively', async () => {
  const f = await fixture(); const ui = await f.load('ui.js');
  const stamp = ui.ageStamp({ ts: 1000 }, 3), status = ui.freshPill({ ts: 1000 }, 'active', 'ok', 3);
  f.document.body.append(stamp, status); ui.refreshAges();
  assert.equal(stamp.textContent, '0.0 s'); assert.equal(status.textContent, 'Active');
  f.advance(4); ui.refreshAges();
  assert.equal(stamp.textContent, '4.0 s · stale'); assert.equal(status.textContent, 'unknown / stale');
});

test('service polling preserves operator expansion and collapsed logs by host and unit identity', async () => {
  const f = await fixture();
  const row = { host: 'pi', unit: 'rider-camera.service', lifecycle: 'on_demand', load: 'loaded', active: 'active', can_move: false, observed_at: 1000 };
  const second = { ...row, unit: 'rider-api.service' };
  f.replies.set('/api/logic/catalog', { ok: true, error: null, operation: null,
    meta: { envelope_version: 1, contract_id: 'rider.catalog', contract_version: 2,
      source_host: 'pi', observed_at: 1000, generated_at: 1000, server_time: 1000, stale: false, offline: false },
    data: { ok: true, contract_version: 2, catalog_version: 2, api_envelope_versions: [1], observed_at: 1000, features: [], units: [row, second] } });
  const services = { contract_version: 2, observed_at: 1000, services: [row, second] };
  f.replies.set('/svc', services); f.replies.set('/api/services/rider-camera.service/logs', { lines: ['fixture only'], source: 'journal', observed_at: 1000 });
  const { System } = await f.load('system.js'); const system = new System({ can: () => false }); await flush();
  const detail = key => f.document.querySelectorAll('details[data-system-detail]').find(node => node.dataset.systemDetail === key);
  detail('autostart:pi:rider-camera.service').open = true;
  detail('source:pi:rider-camera.service').open = true;
  detail('source:system').open = true;
  await system.logs(row);
  assert.equal(detail('logs:pi:rider-camera.service').open, true, 'explicit first log read is visible');
  detail('logs:pi:rider-camera.service').open = false;
  services.services = [second, row]; await system.poller.refresh();
  assert.equal(detail('autostart:pi:rider-camera.service').open, true);
  assert.equal(detail('source:pi:rider-camera.service').open, true);
  assert.equal(detail('source:system').open, true);
  assert.equal(detail('logs:pi:rider-camera.service').open, false);
  assert.equal(detail('autostart:pi:rider-api.service').open, false);
  assert.equal(f.calls.filter(url => url.endsWith('/logs')).length, 1, 'poll never retrieves logs automatically');
  services.services = []; system.render(); services.services = [row]; system.render();
  assert.equal(detail('autostart:pi:rider-camera.service').open, true, 'temporary missing row retains operator preference');
  assert.equal(detail('logs:pi:rider-camera.service').open, false);
});

test('cached navigation parent failures expire nested geometry without restamping its source', async () => {
  const f = await fixture(); const { Navigation } = await f.load('navigation.js'); const model = await f.load('model.js');
  const navigation = new Navigation({ can: () => false, state: null }); await flush();
  const children = { map: { observed_at: 1000, source: 'mapper.map.data', grid: [0] },
    pose: { observed_at: 1000, source: 'robot.pose', x: 0, y: 0, theta: 0 },
    path: { observed_at: 1000, source: 'navigator.path', path: [[0, 0]] } };
  for (const failure of [{ stale: true }, { offline: true }, { error: 'cache unavailable' }, { data_error: 'source invalid' },
    { data_ready: false }, { navigation_ready: false }, { quality: 'UNKNOWN' }, { quality: null }]) {
    navigation.observeSnapshot({ ...children, ...failure });
    for (const name of ['map', 'pose', 'path']) {
      assert.equal(model.presentationReady(navigation[name], 10), false, JSON.stringify(failure));
      assert.equal(navigation[name].observed_at, 1000); assert.equal(navigation[name].source, children[name].source);
    }
  }
  navigation.observeSnapshot(children);
  assert.equal(model.presentationReady(navigation.pose), true, 'new healthy envelope clears prior failure');
  navigation.observeSnapshot(null);
  assert.equal(navigation.map.observed_at, null); assert.equal(navigation.map.grid, undefined);
  assert.equal(navigation.pose.x, undefined); assert.equal(model.presentationReady(navigation.path), false);
});

test('outer proxy failures invalidate cached navigation and cannot confirm a pending task', async () => {
  const f = await fixture(); const { Navigation } = await f.load('navigation.js'); const model = await f.load('model.js');
  f.elements.set('nav-status', new Element());
  const children = { map: { observed_at: 1000, grid: [0] }, pose: { observed_at: 1000, x: 0, y: 0, theta: 0 },
    path: { observed_at: 1000, path: [[0, 0]] } };
  const status = { observed_at: 1000, state: 'EXPLORING', active: true, generation: 'g', request_id: 'r' };
  const navigation = new Navigation({ can: () => false, state: null }); await flush();
  navigation.history = [{ generation: 'g', request_id: 'r', ts: 1000, status: 'pending' }];
  for (const failure of [{ offline: true }, { stale: true }, { error: 'proxy unavailable' }, { data_error: 'source invalid' }]) {
    f.replies.set('/api/navigator/status', { navigation: children, navigator: status, ...failure }); await navigation.poller.refresh();
    assert.ok(f.elements.get('nav-status').textContent.startsWith('unknown / stale'));
    assert.equal(navigation.history[0].status, 'pending');
    for (const name of ['map', 'pose', 'path']) assert.equal(model.presentationReady(navigation[name]), false, JSON.stringify(failure));
  }
  // A fresh failed task is useful status, even when its measurements are unusable.
  f.replies.set('/api/navigator/status', { navigation: children, navigator: { ...status, state: 'FAILED', active: false }, data_ready: false });
  await navigation.poller.refresh();
  assert.ok(f.elements.get('nav-status').textContent.startsWith('FAILED'));
  assert.equal(navigation.history[0].status, 'task_observed'); assert.equal(navigation.history[0].active, false);
  assert.equal(model.presentationReady(navigation.map), true, 'task readiness does not invalidate an independently fresh cached map');
});

test('GPIO power evidence uses the same short LCD label without a renderer event', async () => {
  const f = await fixture(); const { Overview } = await f.load('overview.js');
  f.elements.set('d_lcd', new Element());
  for (const lang of ['pl', 'en']) {
    f.document.documentElement.lang = lang;
    const lcd = { on: false, power_known: true, source: 'lcd-backlight-gpio', power_source: 'lcd-backlight-gpio',
      power_observed_at: 1000, confirmation: 'gpio_level_observed' };
    Overview.prototype.renderTelemetry.call({ state: null, health: { devices: { lcd } } });
    assert.equal(f.elements.get('d_lcd').textContent, 'OFF');
    assert.equal(f.calls.length, 0);
  }
});
