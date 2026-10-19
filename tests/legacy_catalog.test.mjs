import {loadSource} from './helpers/source-module.mjs';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const {blockLegacyButton,legacyBlocked,legacyResourceState}=await loadSource(new URL('../web/assets/legacy-catalog.js',import.meta.url));

test('unavailable and unknown resources are not busy', () => {
  assert.equal(legacyResourceState({ state: 'unavailable', free: null }).state, 'unavailable');
  assert.equal(legacyResourceState({ state: 'unknown', free: null }).state, 'unknown');
  assert.equal(legacyResourceState({ state: 'free', free: null }).state, 'unknown');
  assert.equal(legacyResourceState({ state: 'free', free: true }).state, 'free');
  assert.equal(legacyResourceState({ state: 'busy', free: false }).state, 'busy');
});

test('unsupported legacy actions remain disabled after busy state clears', () => {
  const button = { dataset: {}, disabled: false };
  blockLegacyButton(button);
  assert.equal(button.disabled, true);
  assert.equal(legacyBlocked(button), true);
  assert.match(button.title, /panel operatora v2/);
  assert.equal(legacyBlocked({ dataset: {} }), false);
});
