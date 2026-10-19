import {loadSource} from './helpers/source-module.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const root=new URL('../web/assets/operator/',import.meta.url);
const {telemetrySummary,orientationSummary}=await loadSource(new URL('overview-model.js',root));
const samples = () => Object.fromEntries(['roll','pitch','yaw','battery'].map((name, i) => [name, {ready:true, observed_at:100-i/10,value:i}]));
test('group age uses oldest measurement, not HTTP publication', () => {
  assert.ok(Math.abs(telemetrySummary(samples(),101).age-1.3)<1e-9);
});
test('missing channel cannot look like fresh complete telemetry', () => {
  const rows=samples(); rows.yaw.ready=false;
  assert.deepEqual(telemetrySummary(rows,101),{complete:false,age:null});
});
test('unverified giant yaw is excluded from main orientation', () => {
  const rows=samples(); rows.yaw.value=-4195839;
  assert.equal(orientationSummary(rows),'R 0.0 · P 1.0');
});
