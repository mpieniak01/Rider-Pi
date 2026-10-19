import {loadSource} from './helpers/source-module.mjs';
// Pure functions and source fixtures; no transport, robot SDK or real commands.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
const base = new URL('../web/assets/operator/', import.meta.url);
const model=await loadSource(new URL('calibration-model.js',base));
test('activation timeout expires missing or stale observations without automatic retry', () => {
  const command = { ts: 1000 };
  for (const state of [null, {}, { stale: true }, { motion: { observed_at: null }, odometry: { observed_at: 1000 } },
    { motion: { observed_at: 990 }, odometry: { observed_at: 990 } }]) {
    assert.equal(model.activationPendingResult(state, command, 1008), null);
    assert.deepEqual(model.activationPendingResult(state, command, 1009),
      { status: 'unknown', reason: 'activation_confirmation_timeout_no_retry' });
  }
});
