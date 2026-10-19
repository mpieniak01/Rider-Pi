import {loadSource} from './source-module.mjs';
// In-memory browser fixtures only: no sockets, SDK or hardware.
import { webcrypto } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath, pathToFileURL } from 'node:url';

const assets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../web/assets/operator');
const model = await loadSource(path.join(assets, 'model.js'));
const instant = Date.now() / 1000;
const capability = { available: true, stop_verified: true };
const armed = (now = Date.now() / 1000) => ({ contract_version: 1, state: 'ARMED', generation: 'fixture-generation', owner: 'manual',
  ready: true, hardware_ready: true, can_move: true, read_only: false, observed_at: now, lease_remaining_s: 10, last_seq: 4,
  capabilities: { move: capability, turn: capability, height: { available: false, stop_verified: false, verification: 'manual_characterization_required' } } });
const disarmed = (now = Date.now() / 1000) => ({ ...armed(now), state: 'DISARMED', owner: null, can_move: false, read_only: true });

class Element {
  setAttribute(key, value) { this[key] = value; }
  constructor(id = '') { this.id = id; this.listeners = {}; this.value = ''; this.checked = false; this.disabled = false; this.dataset = {}; this.children = []; this.nodeType = 1; this.classList = { toggle() {}, add() {} }; }
  addEventListener(name, action) { this.listeners[name] = action; }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  closest(selector) { return this.editing && selector.includes('input') ? this : null; }
}
function canonicalReply(contractId, contractVersion, data, now = Date.now() / 1000) {
  return { meta: { envelope_version: 1, contract_id: contractId, contract_version: contractVersion,
    host: 'pi', source: 'pi', observed_at: now, generated_at: now, server_time: now,
    stale: false, offline: false, partial: false }, ok: true, data, error: null, operation: null };
}
function catalogReply(features = [], now = Date.now() / 1000) {
  return canonicalReply('rider.catalog', 2, { contract_version: 2, catalog_version: 2,
    api_envelope_versions: [1], observed_at: now, features, units: [] }, now);
}
async function fixture(initial = disarmed(), { page = 'control', safetyCard = null, clock = null, legacySafety = false, canonicalMime = 'application/vnd.rider.api+json;version=1', interactive = true, catalogDelay = 0, beforeFetch = ()=>null } = {}) {
  const elements = new Map(['global-motion-toggle', 'arm', 'clear-estop', 'disarm', 'estop', 'operator-plan', 'operator-consent', 'control-owner', 'lease',
    'duration', 'speed', 'yaw-speed', 'request-history', 'safety-state', 'safety-owner', 'safety-reason', 'safety-lease', 'operator-message'].map(id => [id, new Element(id)]));
  elements.get('global-motion-toggle').classList = { toggle() {} };
  elements.get('control-owner').value = 'manual'; elements.get('lease').value = '10'; elements.get('duration').value = '.1';
  elements.get('speed').value = '.1'; elements.get('yaw-speed').value = '.18';
  const listeners = {}, timers = new Map(), calls = [];
  let timerId = 0, current = initial; const replies = new Map();
  const document = { hidden: false, documentElement: { lang: 'pl' }, body: { dataset: { page } },
    getElementById: id => elements.get(id), querySelector: selector => selector === '.operator-safety' ? safetyCard : null, querySelectorAll: () => [], createElement: () => new Element(),
    addEventListener: (name, action) => { listeners[name] = action; }, removeEventListener() {} };
  const context = vm.createContext({ document, window: { addEventListener() {} }, console, crypto: webcrypto,
    Date: clock ? class extends Date { static now() { return clock.now * 1000; } } : Date, Math, Number, String, Boolean, JSON, Map, Set, Error, AbortController,
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; }, clearTimeout: id => timers.delete(id),
    setInterval: callback => { timers.set(++timerId, callback); return timerId; }, clearInterval: id => timers.delete(id),
    fetch: async (url, options) => {
      const hook=beforeFetch(url);if(hook)await hook;
      calls.push({ url, ...options, body: options.body ? JSON.parse(options.body) : undefined });
      if (url === '/api/logic/catalog' && clock) clock.now += catalogDelay;
      const now = clock ? clock.now : Date.now() / 1000;
      const state = { safety: current, server_time: now };
      const reply = replies.has(url) ? replies.get(url) : options.method === 'POST' ? { pending: true, confirmed: false }
        : url === '/api/logic/catalog' ? catalogReply([], now)
          : url === '/api/control/state' && !legacySafety ? canonicalReply('rider.safety', 1, state, now) : state;
      return { ok: true, status: options.method === 'POST' ? 202 : 200,
        headers: { get: name => name.toLowerCase() === 'content-type'
          ? reply.meta ? canonicalMime : 'application/json' : null },
        json: async () => reply };
    } });
  const modules = new Map();
  async function load(name) {
    if (modules.has(name)) return modules.get(name);
    const source = await readFile(path.join(assets, name), 'utf8');
    const module = new vm.SourceTextModule(source, { context, identifier: pathToFileURL(path.join(assets, name)).href }); modules.set(name, module);
    await module.link(specifier => load(path.basename(specifier).split("?")[0]));
    return module;
  }
  const module = await load('safety.js'); await module.evaluate();
  const panel = new module.namespace.SafetyPanel(() => {}, { interactive });
  await new Promise(resolve => setImmediate(resolve));
  return { panel, elements, calls, listeners, document, timers, setReply(url, data) { replies.set(url, data); }, async load(name) { const module = await load(name); await module.evaluate(); return module.namespace; }, setState(value) { current = value; panel.update(value); } };
}

export {assets,model,instant,capability,armed,disarmed,Element,fixture,canonicalReply,catalogReply};
