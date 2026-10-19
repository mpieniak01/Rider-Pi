// In-memory DOM and REST: no browser hardware, SPI, UART or motor endpoint.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../web/assets/face-studio.js', import.meta.url), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  class Element {
    constructor() {
      this.value = '';
      this.checked = false;
      this.disabled = false;
      this.style = {};
      this.children = [];
      this.dataset = {};
    }
    add(item) {
      this.children.push(item);
      if (!this.value) {
        this.value = item.value;
      }
    }
    append(...items) {
      this.children.push(...items);
    }
    replaceChildren(...items) {
      this.children = items;
      this.value = '';
    }
    setAttribute(key, value) {
      this[key] = value;
    }
    removeAttribute(key) {
      delete this[key];
    }
    addEventListener(event, fn) {
      this['on' + event] = fn;
    }
    click() {
      this.onclick?.();
    }
    get valueAsNumber() {
      return Number(this.value);
    }
  }
  const elements = new Map(),
    get = id => {
      if (!elements.has(id)) {
        elements.set(id, new Element());
      }
      return elements.get(id);
    };
  for (const [id, value] of Object.entries({
    source: 'draft',
    zoom: '240'
  })) get(id).value = value;
  const events = {},
    jobs = new Map(),
    calls = [];
  let id = 0,
    revision = 'first',
    pending = null,
    hold = false,
    runtime = {
      running: false
    };
  const fields = {
    'eyes.dx': [-1, 1],
    'mouth.open': [0, 1],
    'mouth.curve': [-1, 1]
  };
  let settings = {
    style: 'friendly',
    skin: 'none',
    power_mode: 'battery',
    idle: true,
    intensity: 1,
    tempo: 1,
    transition: 'original',
    active_gestures: ['builtin:happy']
  };
  const descriptors = {
    contract_version: 1,
    styles: [{
      id: 'friendly',
      pl: 'Przyjazna',
      en: 'Friendly'
    }, {
      id: 'minimal',
      pl: 'Prosta',
      en: 'Simple'
    }],
    skins: [{
      id: 'none',
      pl: 'Bez oprawy',
      en: 'No character'
    }, {
      id: 'human',
      pl: 'Piegusek',
      en: 'Freckles'
    }, {
      id: 'cat',
      pl: 'Kotek',
      en: 'Kitten'
    }, {
      id: 'robot',
      pl: 'Robocik',
      en: 'Little robot'
    }, {
      id: 'professional',
      pl: 'Profesjonalna',
      en: 'Professional'
    }],
    expressions: ['neutral', 'happy'],
    expression_defaults: {
      neutral: {
        'mouth.curve': .15
      },
      happy: {
        'mouth.curve': .8
      }
    },
    intensity: {
      min: 0,
      max: 100,
      step: 1
    },
    tempo: {
      min: 50,
      max: 200,
      step: 5
    },
    duration: {
      max: 10000,
      step: 10
    },
    transitions: ['original', 'lin', 'in_out'],
    fps: {
      preview: 12
    }
  };
  const gesture = {
    id: 'builtin:happy',
    builtin: true,
    name: 'happy',
    expr: 'happy',
    duration: 1,
    initial: {
      'mouth.curve': .8
    },
    tracks: {}
  };
  const response = data => ({
    ok: true,
    status: 200,
    json: async () => data,
    blob: async () => new Blob(['PNG']),
    headers: {
      get: () => null
    }
  });
  const document = {
    hidden: false,
    documentElement: {
      lang: 'pl'
    },
    getElementById: get,
    createElement: () => new Element(),
    querySelectorAll: () => [],
    addEventListener: (event, fn) => events[event] = fn
  };
  const fetch = async (url, options = {}) => {
    calls.push({
      url,
      options
    });
    if (url.endsWith('/gestures')) {
      return response({
        gestures: [gesture],
        fields,
        descriptors,
        settings,
        settings_revision: revision
      });
    }
    if (url.endsWith('/runtime')) {
      if (options.method === 'POST') {
        const body = JSON.parse(options.body);
        assert.equal(body.if_revision, revision);
        delete body.if_revision;
        settings = {
          ...settings,
          ...body
        };
        revision = 'saved';
      }
      return response({
        state: runtime,
        settings,
        settings_revision: revision
      });
    }
    if (url.endsWith('/runtime/play') || url.endsWith('/runtime/stop')) {
      return response({});
    }
    if (url.endsWith('/frame')) {
      if (hold) {
        return new Promise((resolve, reject) => {
          pending = resolve;
          options.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {
            name: 'AbortError'
          })));
        });
      }
      return response({});
    }
    throw new Error('Unexpected endpoint ' + url);
  };
  const context = {
    document,
    window: {
      addEventListener: (event, fn) => events[event] = fn
    },
    fetch,
    Option: function (text, value) {
      this.text = text;
      this.value = value;
    },
    setTimeout: (fn, ms) => {
      jobs.set(++id, {
        fn,
        ms
      });
      return id;
    },
    clearTimeout: key => jobs.delete(key),
    URL: {
      createObjectURL: () => 'blob:fixture',
      revokeObjectURL() {}
    },
    Blob,
    AbortController,
    performance: {
      now: () => 1000
    },
    confirm: () => true,
    console
  };
  vm.runInNewContext(source, context, {
    filename: new URL('../web/assets/face-studio.js', import.meta.url).href
  });
  return {
    get,
    document,
    events,
    jobs,
    calls,
    async ready() {
      await flush();
    },
    async frame() {
      const row = [...jobs].find(([, v]) => v.ms === 0);
      assert.ok(row);
      jobs.delete(row[0]);
      row[1].fn();
      await flush();
    },
    hold() {
      hold = true;
    },
    finish() {
      pending?.(response({}));
    },
    runtime(value) {
      runtime = value;
    },
    external(value) {
      settings = {
        ...settings,
        ...value
      };
      revision = 'external';
    }
  };
}
function node() {
  const classes = new Set(),
    listeners = new Map(),
    attributes = new Map();
  return {
    dataset: {},
    children: [],
    style: {},
    textContent: '',
    value: '',
    listeners,
    classList: {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
      contains: name => classes.has(name)
    },
    append(...items) {
      this.children.push(...items);
    },
    replaceChildren(...items) {
      this.children = items;
    },
    addEventListener: (name, fn) => listeners.set(name, fn),
    setAttribute(name, value) {
      attributes.set(name, String(value));
      if (name === 'lang') {
        this.lang = String(value);
      }
    },
    getAttribute: name => attributes.get(name) ?? null,
    querySelectorAll: () => [],
    querySelector: () => null,
    select() {
      this.selected = true;
    },
    remove() {
      this.removed = true;
    },
    focus() {
      this.focused = true;
    }
  };
}
function globals(overrides = {}) {
  const documentElement = node(),
    body = node(),
    events = new Map(),
    jobs = new Map();
  let serial = 0;
  documentElement.lang = 'en';
  const document = {
    documentElement,
    body,
    hidden: false,
    readyState: 'complete',
    querySelectorAll: () => [],
    querySelector: () => null,
    createElement: () => node(),
    addEventListener: (name, fn) => events.set(name, fn)
  };
  const window = {
    i18n: {},
    addEventListener: (name, fn) => events.set(name, fn),
    dispatchEvent: event => events.get(event.type)?.(event)
  };
  class CustomEvent {
    constructor(type, options = {}) {
      this.type = type;
      this.detail = options.detail;
      this.bubbles = options.bubbles ?? false;
      this.cancelable = options.cancelable ?? false;
    }
  }
  return {
    document,
    window,
    events,
    jobs,
    CustomEvent,
    AbortController,
    URL,
    console,
    navigator: {
      language: 'en'
    },
    localStorage: {
      getItem: () => null,
      setItem() {}
    },
    setTimeout: (fn, ms) => {
      jobs.set(++serial, {
        fn,
        ms
      });
      return serial;
    },
    clearTimeout: key => jobs.delete(key),
    fetch: () => assert.fail('Unexpected real-resource fetch'),
    ...overrides
  };
}
async function ownedModule(file, values, expose = '', evaluate = true) {
  let text = await readFile(new URL('../web/assets/' + file, import.meta.url), 'utf8');
  if (expose) {
    const marker = '(function () {';
    assert.ok(text.includes(marker));
    text = text.replace(marker, marker + '\n globalThis.w2={' + expose + '};');
  }
  const context = vm.createContext(values),
    module = new vm.SourceTextModule(text, {
      context
    });
  const translation = new vm.SyntheticModule(['initI18n', 'applyDom', 't'], function () {
    this.setExport('initI18n', () => {});
    this.setExport('applyDom', () => {});
    this.setExport('t', (key, params) => params?.message ? key + ':' + params.message : key);
  }, {
    context
  });
  await module.link(() => translation);
  if (evaluate) {
    await module.evaluate();
  }
  return {
    context,
    module
  };
}
async function footer(values = globals()) {
  return ownedModule('footer.js', values, 'renderVersion,copyCommit,setupUpdateBridge,setupThemeSwitcher,renderPresence');
}
test('JSON document copies preserve normalization and independence rather than structured-clone types', () => {
  const declaration = source.match(/const clone = ([^\n]+);/);
  assert.ok(declaration);
  const clone = vm.runInNewContext('(' + declaration[1] + ')');
  const input = {
    nested: {
      value: 1
    },
    missing: undefined,
    bad: NaN,
    values: [undefined, Infinity],
    when: new Date('2020-01-01T00:00:00Z')
  };
  const copied = clone(input);
  assert.equal(JSON.stringify(copied), JSON.stringify({
    nested: {
      value: 1
    },
    bad: null,
    values: [null, null],
    when: '2020-01-01T00:00:00.000Z'
  }));
  assert.notEqual(copied.nested, input.nested);
  copied.nested.value = 2;
  assert.equal(input.nested.value, 1);
  assert.equal(Object.hasOwn(copied, 'missing'), false);
  let conversions = 0;
  const custom = {
    toJSON() {
      conversions++;
      return {
        document: 'value'
      };
    }
  };
  assert.equal(JSON.stringify(clone(custom)), JSON.stringify({
    document: 'value'
  }));
  assert.equal(conversions, 1);
});
test('clearing an already empty draft image still resets image controls', async () => {
  const f = fixture();
  await f.ready();
  f.get('source').value = 'live';
  f.get('source').onchange();
  f.get('png').disabled = false;
  f.get('studio-image').src = 'stale';
  f.get('source').onchange();
  assert.equal(f.get('png').disabled, true);
  assert.equal(f.get('studio-image').src, undefined);
  assert.equal(f.get('play').disabled, true);
  assert.equal(f.get('speech-preview').disabled, true);
});
for (const action of ['lcd-play', 'lcd-stop']) test(action + ' polls after the action even without a previous timer', async () => {
  const f = fixture();
  await f.ready();
  f.document.hidden = true;
  f.events.visibilitychange();
  await flush();
  assert.equal(f.jobs.size, 0);
  f.document.hidden = false;
  const before = f.calls.filter(row => row.url.endsWith('/runtime')).length;
  await f.get(action).onclick();
  await flush();
  assert.equal(f.calls.filter(row => row.url.endsWith('/runtime')).length, before + 1);
  assert.ok([...f.jobs.values()].some(row => row.ms === 2000));
});
test('footer version labels keep unavailable detached and message precedence', async () => {
  const f = await footer(),
    ctx = {
      branchEl: node(),
      dirtyEl: node(),
      commitBtn: node()
    };
  f.context.w2.renderVersion(ctx, null);
  assert.equal(ctx.branchEl.textContent, 'footer.unavailable');
  assert.equal(ctx.commitBtn.disabled, true);
  f.context.w2.renderVersion(ctx, {
    available: true,
    commit: 'abc1234',
    branch: 'HEAD',
    dirty: true,
    message: 'fixture message'
  });
  assert.equal(ctx.branchEl.textContent, 'footer.detached');
  assert.equal(ctx.commitBtn.title, 'footer.last_commit:fixture message');
  assert.equal(ctx.dirtyEl.hidden, false);
  f.context.w2.renderVersion(ctx, {
    available: true,
    commit: 'abc1234',
    branch: 'feature'
  });
  assert.equal(ctx.branchEl.textContent, 'feature');
  assert.equal(ctx.commitBtn.title, 'footer.copy');
});
test('footer updates ignore inherited keys and support null-prototype or shadowed inputs', async () => {
  const values = globals(),
    f = await footer(values),
    ctx = {
      presencePill: node(),
      presenceState: node(),
      modeEl: node(),
      confEl: node(),
      modeLabel: 'mode',
      confLabel: 'conf'
    };
  f.context.w2.setupUpdateBridge([ctx], []);
  const state = {
    observed_at: Date.now() / 1000,
    present: true,
    mode: 'fixture',
    confidence: .5
  };
  const partial = Object.create(null);
  partial.state = state;
  partial.hasOwnProperty = null;
  values.window.dashboardFooter.update(partial);
  assert.equal(ctx.presenceState.textContent, 'ACTIVE');
  values.window.dashboardFooter.update(Object.create({
    state: {
      present: false
    },
    snapInfo: {},
    cameraResource: {}
  }));
  assert.equal(ctx.presenceState.textContent, 'ACTIVE');
  values.window.dashboardFooter.update({
    state: null
  });
  assert.equal(ctx.presenceState.textContent, '—');
});
for (const copied of [true, false]) test('HTTP clipboard fallback cleans up and restores focus (' + copied + ')', async () => {
  const values = globals(),
    focused = node(),
    inputs = [];
  values.document.activeElement = focused;
  values.document.createElement = () => {
    const input = node();
    inputs.push(input);
    return input;
  };
  let commands = 0;
  values.document.execCommand = command => {
    assert.equal(command, 'copy');
    commands++;
    return copied;
  };
  const f = await footer(values),
    button = node();
  button.title = 'original title';
  await f.context.w2.copyCommit(button, 'abc1234');
  assert.equal(commands, 1);
  assert.equal(inputs[0].selected, true);
  assert.equal(inputs[0].removed, true);
  assert.equal(focused.focused, true);
  if (copied) {
    assert.equal(button.textContent, 'footer.copied');
    const timer = [...values.jobs.values()].find(row => row.ms === 1500);
    assert.ok(timer);
    timer.fn();
    assert.equal(button.textContent, '#abc1234');
    assert.equal(button.title, 'original title');
  } else {
    assert.equal(button.title, 'footer.copy_failed');
  }
});
test('theme loader keeps option order dataset visibility and normalization', async () => {
  const values = globals(),
    skin = node(),
    page = node(),
    saved = [];
  skin.dataset.themeSkin = 'v2, v3';
  page.dataset.themePage = 'classic';
  values.localStorage = {
    getItem: () => 'V3',
    setItem: (key, value) => saved.push([key, value])
  };
  values.document.querySelectorAll = selector => selector.includes('skin') ? [skin] : [page];
  const text = await readFile(new URL('../web/assets/theme-loader.js', import.meta.url), 'utf8');
  vm.runInNewContext(text, values);
  assert.equal(values.document.documentElement.dataset.dashboardTheme, 'v3');
  assert.equal(skin.disabled, false);
  assert.equal(page.disabled, true);
  assert.equal(values.window.dashboardTheme.get(), 'v3');
  values.window.dashboardTheme.set('invalid');
  assert.equal(values.document.documentElement.dataset.dashboardTheme, 'classic');
  assert.equal(page.disabled, false);
  assert.equal(JSON.stringify(saved), JSON.stringify([['dashboard_theme', 'classic']]));
  assert.equal(values.window.dashboardTheme.options.map(item => item.value).join(','), 'classic,classic-plus,v2,v3');
});
test('i18n uses dataset values and preserves language-event detail and translated attributes', async () => {
  const values = globals(),
    label = node(),
    attribute = node(),
    received = [];
  label.dataset = {
    i18n: 'footer.last_commit',
    i18nParams: '{"message":"fixture"}'
  };
  attribute.dataset = {
    i18nAttr: 'title:footer.copy'
  };
  values.document.querySelectorAll = selector => selector === '[data-i18n]' ? [label] : [attribute];
  values.window.dispatchEvent = event => received.push(event);
  const f = await ownedModule('i18n.js', values);
  f.module.namespace.initI18n('en');
  assert.equal(label.textContent, f.module.namespace.t('footer.last_commit', {
    message: 'fixture'
  }));
  assert.equal(attribute.getAttribute('title'), f.module.namespace.t('footer.copy'));
  assert.equal(received[0].detail.lang, 'en');
  assert.equal(received[0].bubbles, false);
  assert.equal(received[0].cancelable, false);
  f.module.namespace.setLang('pl');
  assert.equal(received.at(-1).detail.lang, 'pl');
  assert.equal(values.document.documentElement.lang, 'pl');
});
async function menu(values = globals()) {
  let text = await readFile(new URL('../web/assets/menu.js', import.meta.url), 'utf8');
  text = text.replace('(function(){', '(function(){ globalThis.w2={highlightActive,initLangSwitch};');
  vm.runInNewContext(text, values);
  return values;
}
test('menu path matching strips only trailing slashes in linear time', async () => {
  const values = globals(),
    link = node();
  link.href = '/a//b/';
  link.dataset.page = 'fixture';
  values.window.location = {
    pathname: '/a//b' + '/'.repeat(200000),
    origin: 'http://fixture'
  };
  await menu(values);
  values.w2.highlightActive([link]);
  assert.equal(link.classList.contains('is-active'), true);
  const root = node();
  root.href = '/';
  root.dataset.page = 'root';
  values.window.location.pathname = '////';
  values.w2.highlightActive([root]);
  assert.equal(root.classList.contains('is-active'), true);
});
test('menu fallback language changes dispatch a native CustomEvent and retain falsy normalization', async () => {
  const values = globals(),
    button = node(),
    received = [];
  button.dataset.lang = 'en';
  const container = {
      querySelectorAll: () => [button]
    },
    nav = {
      querySelector: () => container
    };
  values.window.i18n = null;
  values.window.dispatchEvent = event => received.push(event);
  await menu(values);
  values.w2.initLangSwitch(nav);
  button.listeners.get('click')();
  assert.equal(values.document.documentElement.lang, 'en');
  assert.equal(received[0].detail.lang, 'en');
  values.events.get('dashboard:langchange')({
    detail: {
      lang: 0
    }
  });
  assert.equal(button.getAttribute('aria-pressed'), 'false');
});
test('system module arms its interval while the first read is pending and prevents duplicate reads', async () => {
  const values = globals(),
    nodes = new Map(['system-graph', 'system-table', 'system-summary', 'system-network', 'status-line'].map(id => [id, node()]));
  nodes.get('system-table').tHead = node();
  nodes.get('system-table').tBodies = [node()];
  values.document.getElementById = id => nodes.get(id);
  let resolveFirst,
    tick,
    calls = 0;
  const response = {
    ok: true,
    json: async () => ({
      nodes: []
    })
  };
  values.fetch = () => {
    calls++;
    return calls === 1 ? new Promise(resolve => resolveFirst = resolve) : Promise.resolve(response);
  };
  values.setInterval = (fn, ms) => {
    assert.equal(ms, 5000);
    tick = fn;
    return 1;
  };
  const loaded = await ownedModule('pages/system.js', values, '', false);
  const evaluating = loaded.module.evaluate();
  assert.equal(await Promise.race([evaluating.then(() => true), flush().then(() => false)]), true);
  assert.equal(calls, 1);
  assert.equal(typeof tick, 'function');
  await tick();
  assert.equal(calls, 1);
  resolveFirst(response);
  await flush();
  await tick();
  assert.equal(calls, 2);
});
test('clean state does not prompt but dirty gestures retain modern and legacy unload protection', async () => {
  const f = fixture();
  await f.ready();
  let prevented = 0;
  const event = {
    preventDefault() {
      prevented++;
    },
    returnValue: 'untouched'
  };
  f.events.beforeunload(event);
  assert.equal(prevented, 0);
  assert.equal(event.returnValue, 'untouched');
  f.get('name').value = 'changed';
  f.get('name').oninput();
  f.events.beforeunload(event);
  assert.equal(prevented, 1);
  assert.equal(event.returnValue, '');
});
test('frame captions preserve live precedence over speech preview', async () => {
  const f = fixture();
  await f.ready();
  await f.frame();
  assert.equal(f.get('image-caption').textContent, 'Podgląd gestu · bez LCD');
  f.get('speech-preview').checked = true;
  f.get('speech-preview').onchange();
  await f.frame();
  assert.equal(f.get('image-caption').textContent, 'Podgląd · symulacja mówienia');
  f.get('source').value = 'live';
  f.get('source').onchange();
  await f.frame();
  assert.equal(f.get('image-caption').textContent, 'Obraz aktywnego wykonawcy buźki.');
});
for (const [state, expected] of [[{
  running: false
}, 'Buźka wyłączona · bateria'], [{
  running: true,
  sink: 'fixture',
  fps: 12
}, 'Buźka działa · fixture · 12 FPS'], [{
  running: true,
  error: 'face_not_running'
}, 'Buźka nie jest uruchomiona.']]) test('runtime status preserves error/running precedence: ' + expected, async () => {
  const f = fixture();
  await f.ready();
  f.runtime(state);
  const timer = [...f.jobs].find(([, row]) => row.ms === 2000);
  assert.ok(timer);
  f.jobs.delete(timer[0]);
  await timer[1].fn();
  await flush();
  assert.equal(f.get('runtime-status').textContent, expected);
});
