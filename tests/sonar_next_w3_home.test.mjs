// The actual home module runs with inert DOM, fetch promises and recorded timers.
import test, {before} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const file = new URL('../web/home.html', import.meta.url);
const html = await readFile(file, 'utf8');
const inline = /<script type="module">([\s\S]*?)<\/script>/.exec(html);
let source;
before(() => {
  assert.ok(inline);
  const prefix = html.slice(0, inline.index + inline[0].indexOf(inline[1]));
  source = '\n'.repeat(prefix.split('\n').length - 1) + inline[1];
});
const flush = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
  const ids = ['stateBadge', 'stateValue', 'timestampValue', 'requestsValue', 'errorsValue', 'snapshotData'];
  const nodes = new Map(ids.map(id => [id, {textContent: '', className: ''}]));
  const calls = [], intervals = [], errors = [];
  const context = vm.createContext({
    document: {querySelector: selector => nodes.get(selector.slice(1))},
    console: {error: (...values) => errors.push(values)},
    fetch(url, options) {
      return new Promise((resolve, reject) => calls.push({url, options, resolve, reject}));
    },
    setInterval: (fn, ms) => intervals.push({fn, ms}),
  });
  const module = new vm.SourceTextModule(source, {context, identifier: file.href});
  return {
    nodes, calls, intervals, errors,
    async start() {
      await module.link(() => assert.fail('Unexpected module dependency'));
      this.evaluation = module.evaluate();
      await flush();
    },
    reply(index, data, status = 200) {
      calls[index].resolve({status, json: async () => data});
    },
  };
}

test('pending initial reads do not delay module completion or the five-second poll registration', async () => {
  const f = fixture();
  await f.start();
  assert.equal(f.calls.length, 2);
  assert.equal(f.intervals.length, 1);
  assert.equal(f.intervals[0].ms, 5000);
  assert.deepEqual(f.calls.map(call => call.url), ['/api/google/status', '/api/google/raw/last.json']);
  assert.ok(f.calls.every(call => call.options.cache === 'no-store'));
  assert.ok(f.calls.every(call => call.options.method === undefined));
  // The next scheduled read can start even when the first two fetch promises remain pending.
  const polling = f.intervals[0].fn();
  assert.equal(f.calls.length, 4);
  f.reply(0, {state: 'off'});
  f.reply(1, {}, 404);
  f.reply(2, {state: 'ok'});
  f.reply(3, {}, 404);
  await polling;
});

test('successful status and snapshot preserve text-only values, defaults and badge classes', async () => {
  const f = fixture();
  await f.start();
  f.reply(0, {state: 'ok', timestamp: 0, metrics: {requests_24h: 9}});
  f.reply(1, {label: '<img src=x onerror=alert(1)>', value: 4});
  await flush();
  assert.equal(f.nodes.get('stateBadge').textContent, 'OK');
  assert.equal(f.nodes.get('stateBadge').className, 'c-pill ok');
  assert.equal(f.nodes.get('stateValue').textContent, 'ok');
  assert.equal(f.nodes.get('timestampValue').textContent, '—');
  assert.equal(f.nodes.get('requestsValue').textContent, 9);
  assert.equal(f.nodes.get('errorsValue').textContent, 0);
  assert.equal(f.nodes.get('snapshotData').textContent, JSON.stringify({label: '<img src=x onerror=alert(1)>', value: 4}, null, 2));
  assert.equal(f.errors.length, 0);
});

test('snapshot 404 does not parse a body and status failure still allows subsequent recovery', async () => {
  const f = fixture();
  await f.start();
  f.calls[0].reject(new Error('injected status failure'));
  f.calls[1].resolve({status: 404, json: () => assert.fail('404 body must not be read')});
  await flush();
  assert.equal(f.nodes.get('stateValue').textContent, 'error');
  assert.equal(f.nodes.get('stateBadge').className, 'c-pill err');
  assert.equal(f.nodes.get('snapshotData').textContent, 'No snapshot available yet');
  const polling = f.intervals[0].fn();
  f.reply(2, {state: 'enabled'});
  f.calls[3].reject(new Error('injected snapshot failure'));
  await polling;
  assert.equal(f.nodes.get('stateValue').textContent, 'enabled');
  assert.equal(f.nodes.get('stateBadge').className, 'c-pill warn');
  assert.equal(f.nodes.get('snapshotData').textContent, 'Error loading snapshot');
  assert.equal(f.errors.length, 2);
  assert.equal(f.intervals.length, 1);
});
