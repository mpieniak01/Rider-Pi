import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';
const root = new URL('../web/assets/operator/', import.meta.url);
const context = vm.createContext({ Date });
const model = new vm.SourceTextModule(await readFile(new URL('model.js', root), 'utf8'), { context });
await model.link(() => {}); await model.evaluate();
const gate = new vm.SourceTextModule(await readFile(new URL('service-actions.js', root), 'utf8'), { context });
await gate.link(() => model); await gate.evaluate();
const block = gate.namespace.serviceActionBlock;
const now = Date.now() / 1000;
const row = { unit: 'camera-capture@raw.service', observed_at: now, load: 'loaded', can_move: false,
  permissions: Object.fromEntries(['start', 'stop', 'restart', 'disable'].map(a => [a, { allowed: true }])) };
const state = { catalog: { contract_version: 2, catalog_version: 2, observed_at: now, features: [], units: [] },
  services: { contract_version: 2, observed_at: now }, busy: new Set(), safety: { can: () => false } };
test('nonmoving service actions are available without an administration switch', () => {
  for (const action of ['start', 'stop', 'restart', 'disable']) assert.equal(block(row, action, state), null);
});
test('API permission denial and missing permissions block protected operations', () => {
  assert.equal(block(row, 'enable', state), 'permission_unknown');
  assert.equal(block({ ...row, permissions: { stop: { allowed: false, reason: 'forbidden_on_api' } } }, 'stop', state), 'forbidden_on_api');
  assert.equal(block({ ...row, permissions: { enable: { allowed: false, reason: 'on_demand_autostart_forbidden' } } }, 'enable', state), 'on_demand_autostart_forbidden');
});
test('stale state, pending operations and missing runtime block start', () => {
  assert.equal(block(row, 'start', { ...state, services: { ...state.services, observed_at: now - 11 } }), 'service_data_unavailable');
  assert.equal(block(row, 'start', { ...state, busy: new Set([row.unit]) }), 'operation_pending');
  assert.equal(block({ ...row, start_available: false, start_unavailable_reason: 'runtime_missing' }, 'start', state), 'runtime_missing');
});
test('moving services require their owner authorization while stopping stays available', () => {
  const moving = { ...row, can_move: true, motion_owner: 'navigation' };
  assert.equal(block(moving, 'start', state), 'motion_authorization_required');
  assert.equal(block(moving, 'stop', state), null);
  assert.equal(block(moving, 'restart', { ...state, safety: { can: owner => owner === 'navigation' } }), null);
});
