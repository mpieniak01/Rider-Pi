// In-memory boundary objects only; no browser, sockets or hardware resources.
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';

export const assets = new URL('../../web/assets/', import.meta.url);
export const settle = () => new Promise(resolve => setImmediate(resolve));
export class Node {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.nodeType = 1; this.children = []; this.dataset = {};
    this.attributes = new Map(); this.listeners = new Map(); this.routes = new Map();
    this.style = {}; this.value = ''; this.className = ''; this._text = '';
    this.classList = {
      add: name => this.classList.toggle(name, true), remove: name => this.classList.toggle(name, false),
      contains: name => this.className.split(' ').includes(name),
      toggle: (name, value) => {
        const classes = new Set(this.className.split(' ').filter(Boolean));
        const enabled = value ?? !classes.has(name);
        if (enabled) classes.add(name); else classes.delete(name);
        this.className = [...classes].join(' '); return enabled;
      },
    };
  }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(value) { this.markup = value; } // Static template boundaries are preseeded by fixtures.
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  replaceChildren(...nodes) { this._text = ''; this.children = []; this.append(...nodes); }
  descendants() { return this.children.flatMap(node => [node, ...node.descendants()]); }
  querySelectorAll(selector) {
    return this.descendants().filter(node => {
      if (selector.startsWith('#')) return node.id === selector.slice(1);
      if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
      if (selector.startsWith('[')) return [...selector.matchAll(/\[([^\]]+)\]/g)].every(([, key]) => node.attributes.has(key));
      return node.tagName.toLowerCase() === selector;
    });
  }
  querySelector(selector) { return this.routes.get(selector) ?? this.querySelectorAll(selector)[0] ?? null; }
  setAttribute(key, value) { this.attributes.set(key, String(value)); if (key === 'id') this.id = String(value); }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  removeAttribute(key) { this.attributes.delete(key); delete this[key]; }
  addEventListener(event, fn) { if (!this.listeners.has(event)) this.listeners.set(event, []); this.listeners.get(event).push(fn); }
  async fire(event, data = {}) { for (const fn of this.listeners.get(event) || []) await fn({target: this, ...data}); }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  remove() { this.removed = true; }
}
export function environment(ids = [], page = 'devices') {
  const nodes = new Map(ids.map(id => { const node = new Node(); node.id = id; return [id, node]; }));
  const main = new Node('main'), body = new Node('body'), html = new Node('html');
  html.lang = 'en'; body.dataset.page = page;
  const events = new Map(), documentEvents = new Map(), jobs = new Map(), calls = [], errors = [];
  let jobId = 0;
  const globals = {
    document: {hidden: false, documentElement: html, body, activeElement: null,
      getElementById: id => nodes.get(id) || main.descendants().find(node => node.id === id) || null,
      querySelector: selector => selector === 'main' ? main : null,
      querySelectorAll: () => [], createElement: tag => new Node(tag),
      addEventListener: (event, fn) => documentEvents.set(event, fn)},
    window: {addEventListener: (event, fn) => { if (!events.has(event)) events.set(event, []); events.get(event).push(fn); }},
    Date: class extends Date { static now() { return 1000000; } },
    setTimeout: (fn, ms) => { jobs.set(++jobId, {fn, ms, type: 'timeout'}); return jobId; },
    clearTimeout: id => jobs.delete(id),
    setInterval: (fn, ms) => { jobs.set(++jobId, {fn, ms, type: 'interval'}); return jobId; },
    clearInterval: id => jobs.delete(id),
    AbortController, Blob, URL, Headers, location: {origin: 'http://fixture.invalid'},
    sessionStorage: {getItem: () => null, setItem() {}}, localStorage: {getItem: () => null},
    navigator: {}, console: {error: (...args) => errors.push(args), warn() {}},
    fetch: (...args) => assert.fail('Unconfigured fake fetch: ' + args[0]),
  };
  return {globals, nodes, main, body, events, documentEvents, jobs, calls, errors,
    node: id => nodes.get(id), async emit(event, data = {}) { for (const fn of events.get(event) || []) await fn(data); }};
}
export async function load(file, env, replacements = {}) {
  const context = vm.createContext(env.globals), modules = new Map();
  async function resolve(value) {
    const url = new URL(value); url.search = '';
    if (!modules.has(url.href)) modules.set(url.href, (async () => {
      const replacement = replacements[url.pathname.split('/').at(-1)];
      if (replacement) return new vm.SyntheticModule(Object.keys(replacement), function () {
        for (const [key, value] of Object.entries(replacement)) this.setExport(key, value);
      }, {context, identifier: url.href});
      return new vm.SourceTextModule(await readFile(url, 'utf8'), {context, identifier: url.href});
    })());
    return modules.get(url.href);
  }
  const module = await resolve(new URL(file, assets));
  await module.link((specifier, parent) => resolve(new URL(specifier, parent.identifier)));
  await module.evaluate();
  return module.namespace;
}
export function transport(env, reply = async () => ({data: {}, status: 200})) {
  const pollers = [];
  return {pollers, exports: {
    request: async (path, options = {}) => { env.calls.push({path, ...options}); return reply(path, options); },
    prepareMutation: async () => {},
    poll: (fn, options) => {
      const value = {fn, options, stopped: false, refreshes: 0,
        stop() { this.stopped = true; }, async refresh() { this.refreshes++; return fn(); }};
      pollers.push(value); return value;
    },
  }};
}
