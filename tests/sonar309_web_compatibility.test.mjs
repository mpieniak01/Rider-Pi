// Compatibility proofs execute complete unchanged modules with inert I/O boundaries.
import test from 'node:test';
import assert from 'node:assert/strict';
import { faceFixture, gesture } from './face_studio_fixture.mjs';
import { Node, environment, load, settle } from './helpers/pr308-operator-fixture.mjs';

test('Face Studio JSON-document copy normalizes values and honors toJSON before editor use', async t => {
  let conversions = 0;
  const original = gesture({
    name: 'source name',
    initial: { 'mouth.curve': NaN, missing: undefined },
    when: new Date('2020-01-01T00:00:00Z'),
    toJSON() {
      conversions++;
      return { id: this.id, builtin: false, name: 'document name', expr: this.expr,
        duration: this.duration, initial: this.initial, tracks: this.tracks, when: this.when };
    },
  });
  const f = faceFixture({ gestures: [original] });
  t.after(() => f.hide());
  await f.ready();
  assert.equal(conversions, 1);
  assert.equal(f.get('name').value, 'document name');
  assert.equal(f.pose(0, 'mouth.curve').valueAsNumber, 15); // null from NaN permits expression default.
  f.get('export').onclick();
  const document = JSON.parse(await f.downloads[0].blob.text());
  assert.equal(document.initial['mouth.curve'], null);
  assert.equal(Object.hasOwn(document.initial, 'missing'), false);
  assert.equal(document.when, '2020-01-01T00:00:00.000Z');
  assert.equal(original.initial.missing, undefined);
  assert.ok(Number.isNaN(original.initial['mouth.curve']));
  assert.throws(() => structuredClone(original), { name: 'DataCloneError' });
});

test('structuredClone preserves values that JSON-normalized Face Studio intentionally omits or converts', () => {
  const when = new Date('2020-01-01T00:00:00Z');
  const copied = structuredClone({ missing: undefined, invalid: NaN, when });
  assert.equal(Object.hasOwn(copied, 'missing'), true);
  assert.ok(Number.isNaN(copied.invalid));
  assert.ok(copied.when instanceof Date);
});

for (const dirty of ['none', 'gesture', 'settings']) test('unload compatibility signals for ' + dirty + ' edits', async t => {
  const f = faceFixture();
  t.after(() => f.hide());
  await f.ready();
  if (dirty === 'gesture') {
    f.get('name').value = 'edited';
    f.get('name').oninput();
  }
  if (dirty === 'settings') f.get('idle').onchange();
  const signals = [];
  let returnValue = 'unchanged';
  const event = {
    preventDefault() { signals.push('preventDefault'); },
    get returnValue() { return returnValue; },
    set returnValue(value) { returnValue = value; signals.push('returnValue'); },
  };
  f.events.get('beforeunload')(event);
  assert.deepEqual(signals, dirty === 'none' ? [] : ['preventDefault', 'returnValue']);
  assert.equal(returnValue, dirty === 'none' ? 'unchanged' : '');
});

async function footerBoundary() {
  const f = environment(), target = new Node('footer');
  const commit = new Node('button'), branch = new Node('span');
  commit.setAttribute('data-footer-commit', '');
  branch.setAttribute('data-footer-branch', '');
  target.append(commit, branch);
  f.globals.document.querySelectorAll = selector => selector === '[data-dashboard-footer-target]' ? [target] : [];
  f.globals.window.i18n = {};
  f.globals.fetch = async url => {
    f.calls.push(url);
    if (url === '/web/dashboard_footer_template.html') return { ok: true, text: async () => '<div data-footer-root></div>' };
    assert.equal(url, '/api/status/version');
    return { ok: true, json: async () => ({ available: true, commit: 'abc1234', branch: 'main' }) };
  };
  await load('footer.js', f, { 'i18n.js': { initI18n() {}, applyDom() {}, t: key => key } });
  await settle();
  return { ...f, commit };
}

for (const mode of ['modern', 'http', 'modern-rejected', 'fallback-false', 'fallback-throws']) {
  test('full footer uses clipboard compatibility boundary and cleans up: ' + mode, async () => {
    const f = await footerBoundary(), focused = new Node('input'), operations = [];
    f.globals.document.activeElement = focused;
    if (mode === 'modern' || mode === 'modern-rejected') f.globals.navigator.clipboard = {
      async writeText(value) {
        assert.equal(value, 'abc1234');
        operations.push('writeText');
        if (mode === 'modern-rejected') throw new Error('inert permission denied');
      },
    };
    f.globals.document.execCommand = value => {
      assert.equal(value, 'copy');
      operations.push('execCommand');
      if (mode === 'fallback-throws') throw new Error('inert copy unavailable');
      return mode !== 'fallback-false';
    };
    await f.commit.onclick();
    if (mode === 'modern') {
      assert.deepEqual(operations, ['writeText']);
      assert.equal(f.body.children.length, 0);
      return;
    }
    assert.deepEqual(operations, mode === 'modern-rejected' ? ['writeText', 'execCommand'] : ['execCommand']);
    const input = f.body.children[0];
    assert.equal(input.value, 'abc1234');
    assert.equal(input.selected, true);
    assert.equal(input.removed, true);
    assert.equal(focused.focused, true);
    if (mode.startsWith('fallback-')) {
      assert.equal(f.commit.title, 'footer.copy_failed');
    } else {
      assert.equal(f.commit.textContent, 'footer.copied');
    }
  });
}

test('system diagnostics module completes and arms poll before a held read, then recovers after timeout', async () => {
  const f = environment(['system-graph', 'system-table', 'system-summary', 'system-network', 'status-line']);
  f.node('system-table').tHead = new Node('thead');
  f.node('system-table').tBodies = [new Node('tbody')];
  let observed;
  const started = new Promise(resolve => { observed = resolve; });
  f.globals.fetch = (url, options) => {
    f.calls.push({ url, options });
    if (f.calls.length > 1) return Promise.resolve({ ok: true, json: async () => ({ nodes: [] }) });
    observed();
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('inert timeout'))));
  };
  const loading = load('pages/system.js', f, { 'i18n.js': { initI18n() {}, t: key => key } });
  await started;
  assert.equal(await Promise.race([loading.then(() => true), settle().then(() => false)]), true);
  const interval = [...f.jobs.values()].find(job => job.type === 'interval');
  assert.equal(interval.ms, 5000);
  await interval.fn();
  assert.equal(f.calls.length, 1);
  const timeout = [...f.jobs.values()].find(job => job.ms === 12000);
  timeout.fn();
  await settle();
  assert.equal(f.calls[0].options.signal.aborted, true);
  assert.equal(f.node('status-line').classList.contains('is-stale'), true);
  await interval.fn();
  assert.equal(f.calls.length, 2);
  assert.equal(f.node('status-line').classList.contains('is-stale'), false);
  assert.ok(f.calls.every(call => call.url === '/api/services/graph'));
  assert.ok(f.calls.every(call => call.options.method === undefined));
});
