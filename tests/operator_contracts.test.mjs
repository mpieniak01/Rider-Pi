import {loadSource} from './helpers/source-module.mjs';
// Golden projections only: no network, SDK, service action or physical motion.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const load = name => loadSource(path.join(root,'web/assets/operator',name));
const { decodeResponse, errorMessage, API_ACCEPT, responseFamily } = await load('contract.js');
const { observationChannel } = await load('observations.js');
const { cameraFrame } = await load('model.js');
const fixture = JSON.parse(await readFile(path.join(root, 'tests/fixtures/contracts/rider-v1.json'), 'utf8'));
const options = { now: fixture.now };
test('decoder retains independent envelope/domain versions, null source time and zero values', () => {
  assert.equal(API_ACCEPT, 'application/vnd.rider.api+json;version=1');
  const catalog = decodeResponse(fixture.cases.catalog.body);
  assert.equal(catalog.meta.envelope_version, 1); assert.equal(catalog.meta.contract_version, 2);
  assert.equal(catalog.data.catalog_version, 2); assert.equal(catalog.data.server_time, fixture.now);
  const system = decodeResponse(fixture.cases.unknown_time.body);
  assert.equal(system.data.observed_at, null); assert.equal(system.data.cpu_pct, 0);
  assert.throws(() => decodeResponse({ ...fixture.cases.telemetry.body, meta: { envelope_version: 2 } }));
  assert.throws(() => decodeResponse({ ...fixture.cases.telemetry.body, meta: { ...fixture.cases.telemetry.body.meta, contract_version: 2 } }));
});
test('pending response stays unconfirmed and domain error retains the rejection code', () => {
  const result = decodeResponse(fixture.cases.pending.body, 202);
  assert.equal(result.data.ok, false); assert.equal(result.operation.status, 'pending');
  assert.equal(result.operation.confirmed, false); assert.equal(result.operation.physical_completion, 'unverified');
  const rejected = decodeResponse(fixture.cases.rejected.body, 409);
  assert.equal(rejected.data.error.code, 'motion_estop'); assert.equal(errorMessage(rejected.data.error), 'Emergency stop is active');
});
test('declared envelope must be complete and match the requested domain', () => {
  assert.throws(() => decodeResponse({ meta: {}, data: {} }));
  assert.throws(() => decodeResponse({ meta: null }));
  assert.throws(() => decodeResponse({ ...fixture.cases.telemetry.body, meta: { envelope_version: 1, contract_id: 'unknown' } }));
  assert.throws(() => decodeResponse(fixture.cases.telemetry.body, 200, 'rider.system'));
  assert.equal(responseFamily('/api/status/version'), 'rider.version');
  assert.equal(responseFamily('/vision/snap-info?light=1'), 'rider.frames');
  assert.equal(responseFamily('/api/vision/tracking/mode'), 'rider.tasks');
  assert.equal(decodeResponse(fixture.cases.telemetry.body, 200, 'rider.telemetry').canonical, true);
  const missing = { ...fixture.cases.rejected.body, meta: { ...fixture.cases.rejected.body.meta, contract_id: 'rider.http' } };
  assert.equal(decodeResponse(missing, 404, 'rider.frames').data.error.code, 'motion_estop');
});
test('battery ratio, legacy percent and raw SDK axes use declared formats, including zero', () => {
  const xgo = decodeResponse(fixture.cases.telemetry.body).data.devices.xgo;
  assert.equal(observationChannel(xgo, 'battery', options).value, 50);
  assert.equal(observationChannel(fixture.legacy_rest_percent, 'battery', options).value, 1);
  assert.equal(observationChannel(fixture.legacy_safety_ratio, 'battery', options).value, 100);
  const roll = observationChannel(xgo, 'roll', options);
  assert.equal(roll.value, 0); assert.equal(roll.ready, true); assert.equal(roll.raw_unit, 'sdk_raw');
});
test('one failed axis preserves battery and healthy axes without using a fallback value', () => {
  const xgo = decodeResponse(fixture.cases.partial_telemetry.body).data.devices.xgo;
  assert.equal(observationChannel(xgo, 'battery', options).ready, true);
  assert.equal(observationChannel(xgo, 'roll', options).ready, true);
  assert.equal(observationChannel(xgo, 'yaw', options).ready, false);
  const old = { ...xgo, battery_pct: 100, sensor_quality: { sensors: { battery: { value: null, unit: 'ratio', ready: true, observed_at: fixture.now } } } };
  assert.equal(observationChannel(old, 'battery', options).ready, false);
});
test('unknown time, unit, simulation and stale cache never become fresh on receipt', () => {
  const xgo = fixture.cases.telemetry.body.data.devices.xgo;
  for (const patch of [{ observed_at: null }, { unit: null }, { simulated: true }, { value: Infinity }, { stale: true }]) {
    const sample = { ...xgo, sensor_quality: { sensors: { battery: { ...xgo.sensor_quality.sensors.battery, ...patch } } } };
    assert.equal(observationChannel(sample, 'battery', options).ready, false, JSON.stringify(patch));
  }
  for (const patch of [{ stale: true }, { offline: true }, { meta: { stale: true } }]) {
    assert.equal(observationChannel({ ...xgo, ...patch }, 'battery', options).ready, false);
  }
  assert.equal(observationChannel(xgo, 'battery', { now: fixture.now + 3 }).ready, false);
  assert.equal(observationChannel(xgo, 'battery', { ...options, unavailable: true }).ready, false);
  const failed = decodeResponse(fixture.cases.transport_failure.body, 502);
  assert.equal(failed.data.offline, true); assert.equal(failed.meta.generated_at, fixture.now);
  assert.equal(failed.data.devices.xgo.sensor_quality.sensors.battery.observed_at, 999.8);
});
test('API age assessment is paired with its own time rather than producer publication', () => {
  const xgo = fixture.cases.telemetry.body.data.devices.xgo;
  for (const now of [1001, 1002]) {
    const sample = { ...xgo, generated_at: 1000, sensor_quality: { sensors: {
      battery: { ...xgo.sensor_quality.sensors.battery, age_s: now - 999.8, assessed_at: now }
    } } };
    assert.equal(observationChannel(sample, 'battery', { now }).ready, true);
    assert.ok(Math.abs(observationChannel(sample, 'battery', { now }).age_s - (now - 999.8)) < .001);
    const withoutAssessment = { ...sample.sensor_quality.sensors.battery };
    delete withoutAssessment.assessed_at;
    assert.equal(observationChannel({ ...sample, sensor_quality: { sensors: { battery: withoutAssessment } } }, 'battery', { now }).ready, true);
  }
});
test('explicit file provenance permits an image without inventing its capture time', () => {
  const frames = fixture.cases.frames.body.data;
  assert.equal(cameraFrame(frames, 'proc', fixture.now).fresh, false);
  const row = { exists: true, observed_at: null, capture_at: null, file_observed_at: 999.8,
    provenance: 'file_mtime', stale: false, error: null, max_age_s: 3 };
  const image = cameraFrame({ raw: row }, 'raw', fixture.now);
  assert.equal(image.fresh, true); assert.equal(image.capture_at, null); assert.equal(image.time_basis, 'file_mtime');
  assert.equal(row.observed_at, null);
  assert.equal(cameraFrame({ raw: row }, 'raw', fixture.now + 4).fresh, false);
});
