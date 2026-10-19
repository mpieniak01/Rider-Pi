// Inert browser boundary: execute the entire unchanged source with its real coverage URL.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const sourceURL = new URL('../web/assets/face-studio.js', import.meta.url);
const source = await readFile(sourceURL, 'utf8');
export const flush = () => new Promise(resolve => setImmediate(resolve));
export const reply = (data = {}, status = 200, overrides = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
  blob: async () => new Blob(['PNG'], { type: 'image/png' }),
  ...overrides,
});
export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
export function gesture(overrides = {}) {
  return {
    id: 'user:wave',
    builtin: false,
    name: 'Wave',
    expr: 'neutral',
    duration: 1,
    initial: {},
    tracks: {},
    ...overrides,
  };
}
export function faceFixture(options = {}) {
  const elements = new Map(), events = new Map(), jobs = new Map();
  const calls = [], created = [], revoked = [], downloads = [], confirmations = [];
  const routes = new Map(), objects = new Map();
  let serial = 0, clock = 1000, answer = true;
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag;
      this.children = [];
      this.style = {};
      this.dataset = {};
      this.checked = false;
      this.disabled = false;
      this.textContent = '';
      this._value = '';
    }
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
    get valueAsNumber() { return this.value === '' ? NaN : Number(this.value); }
    append(...items) { this.children.push(...items); }
    add(item) {
      this.children.push(item);
      if (!this.value) this.value = item.value;
    }
    replaceChildren(...items) { this.children = items; this.value = ''; }
    setAttribute(name, value) { this[name] = String(value); }
    removeAttribute(name) { delete this[name]; }
    addEventListener(name, fn) { this['on' + name] = fn; }
    click() {
      if (this.tagName === 'a') downloads.push({ name: this.download, blob: objects.get(this.href), url: this.href });
      return this.onclick?.();
    }
  }
  const get = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  get('source').value = 'draft';
  get('zoom').value = '240';
  const fields = options.fields ?? { 'eyes.dx': [-1, 1], 'mouth.open': [0, 1], 'mouth.curve': [-1, 1] };
  const meta = {
    contract_version: 1,
    styles: [{ id: 'friendly', pl: 'Przyjazna', en: 'Friendly' }, { id: 'minimal', pl: 'Prosta', en: 'Simple' }],
    skins: [{ id: 'none', pl: 'Bez oprawy', en: 'No character' }, { id: 'cat', pl: 'Kotek', en: 'Kitten' }],
    expressions: ['neutral', 'happy', 'custom-expression'],
    expression_defaults: { neutral: { 'mouth.curve': .15 }, happy: { 'mouth.curve': .8 } },
    intensity: { min: 0, max: 100, step: 1 },
    tempo: { min: 50, max: 200, step: 5 },
    duration: { max: 10000, step: 10 },
    transitions: ['original', 'lin', 'in', 'out', 'in_out'],
    fps: { preview: 12 },
  };
  const server = {
    revision: 'first',
    settings: {
      style: 'friendly', skin: 'none', power_mode: 'battery', idle: true,
      intensity: 1, tempo: 1, transition: 'original', active_gestures: ['builtin:happy'],
      ...options.settings,
    },
    runtime: { running: false },
    gestures: options.gestures ?? [
      gesture({ id: 'builtin:happy', builtin: true, name: 'happy', expr: 'happy', initial: { 'mouth.curve': .8 } }),
      gesture(),
    ],
  };
  const labels = options.labels ?? [];
  const document = {
    hidden: options.hidden ?? false,
    documentElement: { lang: options.lang ?? 'en' },
    getElementById: get,
    createElement: tag => { const item = new Element(tag); created.push(item); return item; },
    querySelectorAll: () => labels,
    addEventListener: (name, fn) => events.set(name, fn),
  };
  function queue(path, result, method = 'GET') {
    const key = method + ' ' + path;
    if (!routes.has(key)) routes.set(key, []);
    routes.get(key).push(result);
  }
  for (const row of options.responses ?? []) queue(...row);
  const fetch = async (url, request = {}) => {
    assert.ok(url.startsWith('/api/face-studio/'), 'Unexpected I/O ' + url);
    const path = url.slice('/api/face-studio/'.length), method = request.method ?? 'GET';
    const row = { url, path, method, options: request, body: request.body ? JSON.parse(request.body) : undefined };
    calls.push(row);
    const waiting = routes.get(method + ' ' + path);
    if (waiting?.length) {
      const result = waiting.shift();
      if (result instanceof Error) throw result;
      return typeof result === 'function' ? result(row) : result;
    }
    if (path === 'gestures') {
      if (method === 'POST') {
        const item = { ...row.body, id: row.body.id ?? 'user:saved', builtin: false };
        server.gestures = [...server.gestures.filter(g => g.id !== item.id), item];
        return reply({ id: item.id });
      }
      assert.equal(method, 'GET');
      return reply({ gestures: server.gestures, descriptors: meta, fields, settings: server.settings, settings_revision: server.revision });
    }
    if (path.startsWith('gestures/') && method === 'DELETE') {
      const id = decodeURIComponent(path.slice('gestures/'.length));
      server.gestures = server.gestures.filter(g => g.id !== id);
      return reply({});
    }
    if (path === 'runtime') {
      if (method === 'POST') {
        assert.equal(row.body.if_revision, server.revision);
        const { if_revision, ...settings } = row.body;
        server.settings = { ...server.settings, ...settings };
        server.revision = 'saved';
      }
      return reply({ state: server.runtime, settings: server.settings, settings_revision: server.revision });
    }
    if (path === 'runtime/play' || path === 'runtime/stop') {
      assert.equal(method, 'POST');
      return reply({});
    }
    if (path === 'frame' || path === 'runtime/frame') return reply({});
    throw new Error('Unexpected Face Studio endpoint ' + method + ' ' + path);
  };
  vm.runInNewContext(source, {
    document,
    window: { addEventListener: (name, fn) => events.set(name, fn) },
    fetch,
    Option: function(text, value) { this.text = text; this.value = value; },
    setTimeout: (fn, ms) => { jobs.set(++serial, { fn, ms }); return serial; },
    clearTimeout: id => jobs.delete(id),
    URL: {
      createObjectURL: blob => { const url = 'blob:fixture/' + objects.size; objects.set(url, blob); return url; },
      revokeObjectURL: url => revoked.push(url),
    },
    Blob,
    AbortController,
    performance: { now: () => clock },
    confirm: message => { confirmations.push(message); return answer; },
    console,
  }, { filename: sourceURL.href });
  const startTimer = (ms = 0) => {
    const entry = [...jobs].find(([, job]) => job.ms === ms);
    assert.ok(entry, 'Expected timer ' + ms + '; actual: ' + [...jobs.values()].map(v => v.ms));
    jobs.delete(entry[0]);
    return entry[1].fn();
  };
  return {
    get, server, document, events, jobs, calls, created, revoked, downloads, confirmations, queue,
    fields: Object.keys(fields),
    async ready() { await flush(); await flush(); },
    startTimer,
    async timer(ms = 0) { await startTimer(ms); await flush(); },
    advance(ms) { clock += ms; },
    confirm(value) { answer = value; },
    async hide() { document.hidden = true; events.get('visibilitychange')(); await flush(); },
    pose(row, field) {
      const column = field === 'time' ? 0 : Object.keys(fields).indexOf(field) + 1;
      return get('poses').children[row].children[column].children[0];
    },
    ease(row) { return get('poses').children[row].children[Object.keys(fields).length + 1].children[0]; },
    remove(row) { return get('poses').children[row].children.at(-1).children[0]; },
    select(id = 'user:wave') { get('library').value = id; get('library').onchange(); },
  };
}
