import assert from 'node:assert/strict';
import test from 'node:test';
import {assets,model,instant,capability,armed,disarmed,Element,fixture,canonicalReply,catalogReply} from './helpers/operator-fixture.mjs';

test('movement requires version, fresh observation, state, owner, lease and stop capability', () => {
  const state = armed(instant);
  assert.equal(model.authorized(state, 'manual', 'move', instant), true);
  for (const patch of [{ contract_version: 0 }, { observed_at: instant - 4 }, { observed_at: instant + .2 }, { observed_at: null },
    { state: 'DISARMED' }, { ready: false }, { hardware_ready: false }, { can_move: false }, { read_only: true },
    { owner: 'navigation' }, { lease_remaining_s: 0 }, { lease_remaining_s: 31 }, { lease_remaining_s: Infinity }, { generation: '' },
    { capabilities: { move: { available: true, stop_verified: false } } }]) {
    assert.equal(model.authorized({ ...state, ...patch }, 'manual', 'move', instant), false, JSON.stringify(patch));
  }
  assert.equal(model.authorized(state, 'manual', 'height', instant), false);
});
test('DISARMED read_only is a valid known contract for explicit preparation', () => {
  assert.equal(model.safetyKnown(disarmed(instant), instant), true);
  assert.equal(model.authorized(disarmed(instant), 'manual', 'move', instant), false);
});
test('zero is a measurement; null and stale frame timestamps remain unknown', () => {
  assert.equal(model.displayValue(0, '%'), '0%');
  assert.equal(model.displayValue(null), '—');
  assert.equal(model.cameraFrame({ raw: { exists: true, mtime: instant - 20 } }, 'raw', instant).fresh, false);
  assert.equal(model.cameraFrame({ raw: { exists: true, mtime: null } }, 'raw', instant).age, null);
  for (const flags of [{ offline: true }, { stale: true }, { error: 'camera unavailable' }]) {
    assert.equal(model.cameraFrame({ ...flags, raw: { exists: true, mtime: instant } }, 'raw', instant).fresh, false);
  }
  assert.equal(model.cameraFrame({ raw: { exists: true, stale: true, mtime: instant } }, 'raw', instant).fresh, false);
});
test('old catalog and moving owner mismatch cannot start a task', () => {
  const task = { installed: true, observed_at: instant, state: 'stopped', can_move: true, motion_owner: 'navigation' };
  const catalog = { contract_version: 2, catalog_version: 2, observed_at: instant, features: [task], units: [] };
  assert.equal(model.taskCanStart(task, catalog, armed(instant), instant), false);
  assert.equal(model.taskCanStart(task, { ...catalog, contract_version: 1 }, { ...armed(instant), owner: 'navigation' }, instant), false);
  assert.equal(model.taskCanStart(task, catalog, { ...armed(instant), owner: 'navigation' }, instant), true);
  for (const can_move of [undefined, null]) assert.equal(model.taskCanStart({ ...task, can_move }, catalog, armed(instant), instant), false);
  assert.equal(model.taskCanStart({ ...task, can_move: false }, { ...catalog, offline: true }, armed(instant), instant), false);
});
test('ACK matches action, source, sequence, request and send time; accepted is not execution', () => {
  const command = { request_id: 'fixture', action: 'move', source: 'manual', seq: 5, generation: 'fixture-generation' };
  const ack = { ...command, observed_at: instant, status: 'executed' };
  assert.equal(model.matchingAck(ack, command, instant), true);
  for (const patch of [{ observed_at: instant - .1 }, { status: 'accepted' }, { action: 'stop' }, { seq: 4 }, { source: 'navigation' }, { command_generation: 'another-generation' }]) {
    assert.equal(model.matchingAck({ ...ack, ...patch }, command, instant), false);
  }
});
test('confirmed HTTP ACK uses backend identity confirmation; STOP null sequence is equivalent to absent', () => {
  const command = { request_id: 'stop-fixture', action: 'stop', source: 'manual' };
  const ack = { ...command, seq: null, observed_at: instant - 1, status: 'executed' };
  assert.equal(model.matchingAck(ack, command, instant), false);
  assert.equal(model.matchingAck(ack, command, instant, true), true);
  assert.equal(model.matchingAck({ ...ack, request_id: 'another-request' }, command, instant, true), false);
});
test('server clock bounds tolerate skew without future commands or understating observation age', () => {
  const wall = Date.now() / 1000;
  assert.equal(model.setServerClock(wall + 20, wall - .3, wall), true);
  assert.ok(model.commandSeconds() <= wall + 20.1);
  assert.ok(model.nowSeconds() >= wall + 20.3);
  assert.equal(model.setServerClock(wall + 20, wall - .51, wall), false);
  assert.equal(model.setServerClock(null, wall, wall), false);
  model.setServerClock(Date.now() / 1000, Date.now() / 1000, Date.now() / 1000);
});
test('map world coordinates use mapper additive origin and preserve zero', () => {
  assert.deepEqual(model.gridPoint({ origin_x: 5, origin_y: 3, resolution_m: .1 }, { x: 0, y: 0 }), [50, 30]);
  assert.equal(model.gridPoint({ origin_x: null, origin_y: 3, resolution_m: .1 }, [0, 0]), null);
  assert.equal(model.gridPoint({ origin_x: 1e308, origin_y: 0, resolution_m: .1 }, [1e308, 0]), null);
});

