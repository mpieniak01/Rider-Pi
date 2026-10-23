import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const sourceUrl = new URL('../web/assets/operator/navigation-profile-messages.js', import.meta.url);
const source = await readFile(sourceUrl, 'utf8');
async function load(fetch, locale = 'en') {
  const timers = new Map(); let next = 0;
  const context = vm.createContext({ URL, AbortController, fetch,
    document: { documentElement: { lang: locale } },
    setTimeout(fn, ms) { const id = ++next; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  const module = new vm.SourceTextModule(source, { context, identifier: sourceUrl.href,
    initializeImportMeta(meta) { meta.url = sourceUrl.href; } });
  await module.link(() => assert.fail('Unexpected import')); await module.evaluate();
  assert.equal(timers.size, 0, 'Every loader path releases its deadline timer');
  return { api: module.namespace, timers };
}

test('translation loader validates individual rows and resolves URL relative to the shipped module', async () => {
  let requested;
  const { api } = await load(async (url, options) => {
    requested = url; assert.ok(options.signal instanceof AbortSignal);
    return { ok: true, json: async () => ({ greeting: ['PL {name}', 'EN {name}', 'DE {name}'] }) };
  });
  assert.equal(requested.href, new URL('./navigation-profile-messages.json', sourceUrl).href);
  assert.deepEqual(Object.keys(api.profileMessages), ['greeting']);
  assert.equal(api.profileText('greeting', { name: 'Ada' }), 'EN Ada');
  assert.equal(api.profileText('missing'), 'missing');
});
for (const mode of ['offline', 'http', 'invalid-json', 'null', 'array', 'invalid-row']) {
  test('translation loader fails bounded and retains fallback keys: ' + mode, async () => {
    const { api } = await load(async () => {
      if (mode === 'offline') throw new Error('offline');
      return { ok: mode !== 'http', json: async () => {
        if (mode === 'invalid-json') throw new SyntaxError('bad JSON');
        return mode === 'array' ? [] : mode === 'invalid-row' ? { invalid: ['PL', 42, 'DE'] } : null;
      } };
    });
    assert.equal(api.profileText('behavior.title'), 'behavior.title');
    assert.equal(Object.keys(api.profileMessages).length, 0);
  });
}

test('unsupported locale falls back to Polish while PL and DE retain the selected text', async () => {
  for (const [locale, expected] of [['pl','PL'], ['de','DE'], ['es','PL']]) {
    const { api } = await load(async () => ({ ok: true, json: async () => ({ label: ['PL','EN','DE'] }) }), locale);
    assert.equal(api.profileText('label'), expected);
  }
});
