import test from 'node:test';
import assert from 'node:assert/strict';
import { faceFixture, reply, gesture, deferred, flush } from './face_studio_fixture.mjs';

async function setup(t, options) {
  const f = faceFixture(options);
  t.after(() => f.hide());
  await f.ready();
  return f;
}
const writes = f => f.calls.filter(row => row.method !== 'GET');
const frames = f => f.calls.filter(row => row.path === 'frame');
const status = f => f.get('studio-status').textContent;
const named = (f, name) => f.calls.filter(row => row.path === name);

test('startup metadata populates typed editor bounds and does not activate any worker', async t => {
  const f = await setup(t, { settings: { skin: null }, fields: { 'eyes.dx': [-1, 1], 'custom.field': [-2, 2] } });
  assert.equal(f.get('style').children[0].text, 'Friendly');
  assert.equal(f.get('skin').value, 'none');
  assert.equal(f.get('expression').children.at(-1).text, 'custom-expression');
  assert.equal(f.get('intensity').max, 100);
  assert.equal(f.get('tempo').step, 5);
  assert.equal(f.pose(0, 'time').disabled, true);
  assert.equal(f.pose(1, 'custom.field').min, -200);
  assert.equal(f.get('pose-head').children[0].children[2].textContent, 'custom.field');
  assert.equal(f.get('save').disabled, false);
  assert.equal(f.get('delete').disabled, true);
  assert.equal(writes(f).length, 0);
  assert.match(f.get('runtime-status').textContent, /Face stopped.*battery/);
});

for (const [code, message] of [
  ['lcd_unavailable', 'LCD is unavailable'],
  ['face_settings_conflict', 'Settings changed in another tab'],
  ['name_required', 'Enter a gesture name'],
  ['unknown_gesture', 'Gesture is unavailable'],
  ['gesture_not_active', 'Include the gesture'],
  ['lcd_owned_or_unknown', 'LCD is used by another feature'],
  ['face_not_running', 'The face is not running'],
  ['library_full', 'Library is full'],
  ['unrecognized', 'Operation failed'],
]) test('API failure is visible and keeps unsaved settings: ' + code, async t => {
  const f = await setup(t);
  f.get('idle').checked = false;
  f.get('idle').onchange();
  f.queue('runtime', reply({ ok: false, error: code }, code === 'unrecognized' ? 409 : 200), 'POST');
  await f.get('apply').onclick();
  assert.ok(status(f).includes(message));
  assert.equal(f.get('lcd-play').disabled, true);
  assert.equal(f.get('settings-status').textContent, 'Unsaved preview settings.');
  assert.equal(named(f, 'runtime/play').length, 0);
});

test('startup REST failure and JSON decoding failure remain visible without timers or POST', async t => {
  const f = await setup(t, { responses: [['gestures', reply({ error: 'unknown_gesture' }, 404)]] });
  assert.match(status(f), /Gesture is unavailable/);
  assert.equal(f.jobs.size, 0);
  f.get('play').onclick();
  assert.equal(writes(f).length, 0);
  const g = await setup(t, { responses: [['gestures', reply({}, 200, { json: async () => { throw new Error('invalid JSON'); } })]] });
  assert.equal(status(g), 'invalid JSON');
  assert.equal(g.jobs.size, 0);
});

for (const [ease, expected] of [['in', 25], ['out', 75], ['in_out', 50], ['lin', 50]]) {
  test('real track sampling respects ' + ease + ' easing and segment boundaries', async t => {
    const item = gesture({ tracks: {
      'eyes.dx': [{ t0: 0, t1: 1, v0: 0, v1: 1, ease }],
      'mouth.open': [{ t0: .5, t1: 1, v0: .1, v1: .9, ease: 'lin' }],
    } });
    const f = await setup(t, { gestures: [item] });
    assert.equal(f.get('poses').children.length, 3);
    assert.equal(f.pose(0, 'eyes.dx').valueAsNumber, 0);
    assert.equal(f.pose(1, 'eyes.dx').valueAsNumber, expected);
    assert.equal(f.pose(2, 'eyes.dx').valueAsNumber, 100);
    assert.equal(f.pose(0, 'mouth.open').valueAsNumber, 0);
    assert.equal(f.pose(0, 'mouth.curve').valueAsNumber, 15);
  });
}

test('editing a pose and transition rebuilds the saved track with original units', async t => {
  const f = await setup(t);
  f.select();
  f.pose(1, 'eyes.dx').value = 40;
  f.pose(1, 'eyes.dx').oninput();
  f.ease(1).value = 'out';
  f.ease(1).onchange();
  assert.equal(status(f), 'Unsaved gesture.');
  assert.equal(f.get('update').disabled, false);
  assert.equal(f.get('lcd-play').disabled, true);
  await f.get('update').onclick();
  const saved = writes(f).find(row => row.path === 'gestures').body;
  assert.equal(saved.id, 'user:wave');
  assert.equal(saved.tracks['eyes.dx'][0].v1, .4);
  assert.equal(saved.tracks['eyes.dx'][0].ease, 'out');
  assert.equal(saved.tracks['eyes.dx'][0].t1, 1);
  assert.equal(saved.contract_version, 1);
  assert.match(status(f), /Gesture saved/);
  assert.equal(named(f, 'runtime/play').length, 0);
});

for (const [field, value, expected] of [
  ['time', 0, 'Times must increase.'],
  ['time', 10001, 'Times must increase.'],
  ['time', 'not-a-number', 'Times must increase.'],
  ['eyes.dx', 101, 'Check value ranges.'],
  ['eyes.dx', -101, 'Check value ranges.'],
  ['mouth.open', 'not-a-number', 'Check value ranges.'],
]) test('invalid pose disables saving: ' + field + '=' + value, async t => {
  const f = await setup(t);
  f.pose(1, field).value = value;
  f.pose(1, field).oninput();
  assert.equal(status(f), expected);
  assert.equal(f.get('save').disabled, true);
  assert.equal(f.get('update').disabled, true);
  f.get('play').onclick();
  await f.timer();
  assert.equal(frames(f).length, 0);
});

test('pose removal enforces an ending pose and adding respects the 33-pose cap', async t => {
  const f = await setup(t);
  f.remove(1).onclick();
  assert.equal(status(f), 'Add an ending pose.');
  assert.equal(f.get('save').disabled, true);
  f.get('add').onclick();
  assert.equal(f.get('save').disabled, false);
  for (let i = 0; i < 31; i++) f.get('add').onclick();
  assert.equal(f.get('poses').children.length, 33);
  f.get('add').onclick();
  assert.equal(f.get('poses').children.length, 33);
  assert.equal(status(f), 'Maximum 33 poses');
});

test('discard confirmation protects library and new gestures, while copying clears identity', async t => {
  const f = await setup(t);
  f.get('name').value = 'local edit';
  f.get('name').oninput();
  f.confirm(false);
  f.select();
  assert.equal(f.get('library').value, 'builtin:happy');
  f.get('new').onclick();
  assert.equal(f.get('name').value, 'local edit');
  f.confirm(true);
  f.get('new').onclick();
  assert.equal(f.get('name').value, 'New gesture');
  assert.equal(f.get('active-gesture').disabled, true);
  f.get('copy').onclick();
  assert.equal(f.get('name').value, 'New gesture — copy');
  assert.equal(f.get('update').disabled, true);
  await f.get('save').onclick();
  assert.equal(writes(f).find(row => row.path === 'gestures').body.id, undefined);
  assert.equal(f.get('library').value, 'user:saved');
  f.get('expression').value = 'happy';
  f.get('expression').onchange();
  assert.equal(f.pose(0, 'mouth.curve').valueAsNumber, 80);
  assert.equal(status(f), 'Unsaved gesture.');
});

test('save and delete failures preserve the draft, then confirmed delete encodes the id', async t => {
  const id = 'user:wave / special';
  const f = await setup(t, { gestures: [gesture({ id })] });
  f.queue('gestures', reply({ error: 'name_required' }, 400), 'POST');
  await f.get('save').onclick();
  assert.equal(status(f), 'Enter a gesture name.');
  f.confirm(false);
  await f.get('delete').onclick();
  assert.equal(writes(f).filter(row => row.method === 'DELETE').length, 0);
  f.confirm(true);
  const path = 'gestures/' + encodeURIComponent(id);
  f.queue(path, reply({ error: 'unknown_gesture' }, 404), 'DELETE');
  await f.get('delete').onclick();
  assert.match(status(f), /Gesture is unavailable/);
  await f.get('delete').onclick();
  assert.equal(f.server.gestures.length, 0);
  assert.equal(writes(f).filter(row => row.path === path).length, 2);
});

test('JSON and PNG downloads keep exact payloads and revoke object URLs', async t => {
  const f = await setup(t);
  f.get('png').onclick();
  assert.equal(f.downloads.length, 0);
  await f.timer();
  const firstImage = f.get('studio-image').src;
  f.get('png').onclick();
  f.get('export').onclick();
  assert.equal(f.downloads[0].name, 'face-frame.png');
  assert.equal(await f.downloads[0].blob.text(), 'PNG');
  const exported = JSON.parse(await f.downloads[1].blob.text());
  assert.equal(f.downloads[1].name, 'face-gesture.json');
  assert.equal(exported.id, undefined);
  assert.equal(exported.builtin, undefined);
  assert.equal(exported.expr, 'happy');
  f.get('rewind').onclick();
  await f.timer();
  assert.ok(f.revoked.includes(firstImage));
  await f.timer(1000);
  await f.timer(1000);
  for (const download of f.downloads) assert.ok(f.revoked.includes(download.url));
});

for (const [input, expected] of [
  [null, null],
  [{ size: 65537, text: async () => '{}' }, 'Max 64 KB'],
  [{ size: 1, text: async () => '{' }, 'JSON'],
]) test('import rejects absent oversized or malformed files: ' + expected, async t => {
  const f = await setup(t);
  const previous = status(f);
  f.get('import').value = 'selected';
  f.get('import').files = input ? [input] : [];
  await f.get('import').onchange();
  if (expected) assert.ok(status(f).includes(expected));
  else assert.equal(status(f), previous);
  assert.equal(f.get('import').value, '');
  assert.equal(frames(f).length, 0);
});

test('import validates with real frame request and strips stored identity from the draft', async t => {
  const f = await setup(t);
  f.get('import').files = [{ size: 20, text: async () => JSON.stringify({ name: '<draft>', id: 'forged', builtin: true }) }];
  f.queue('frame', reply({}, 422), 'POST');
  await f.get('import').onchange();
  assert.equal(status(f), 'Invalid gesture.');
  await f.get('import').onchange();
  assert.match(status(f), /Imported as a draft/);
  assert.equal(f.get('name').value, '<draft>');
  assert.equal(f.get('update').disabled, true);
  const imported = frames(f).at(-1).body;
  assert.equal(imported.id, undefined);
  assert.equal(imported.expr, 'neutral');
  assert.equal(imported.duration, 1);
  assert.deepEqual(imported.initial, {});
  assert.equal(imported.at, 0);
  assert.equal(named(f, 'runtime/play').length, 0);
  f.confirm(false);
  const count = frames(f).length;
  await f.get('import').onchange();
  assert.equal(frames(f).length, count);
});

test('preview play pause rewind zoom and looping honor the simulated clock', async t => {
  const f = await setup(t);
  f.get('play').onclick();
  f.advance(1500);
  await f.timer();
  assert.equal(frames(f).at(-1).body.at, 1);
  assert.equal(f.get('time').textContent, '1000 ms');
  assert.equal([...f.jobs.values()].some(job => job.ms === 1000 / 12), false);
  f.get('play').onclick();
  f.advance(250);
  await f.timer();
  assert.equal(frames(f).at(-1).body.at, .25);
  f.get('pause').onclick();
  const count = frames(f).length;
  await f.timer();
  assert.equal(frames(f).length, count);
  f.get('rewind').onclick();
  await f.timer();
  assert.equal(frames(f).at(-1).body.at, 0);
  f.get('zoom').value = 480;
  f.get('zoom').onchange();
  assert.equal(f.get('studio-image').style.maxWidth, '480px');
  f.get('loop').checked = true;
  f.get('play').onclick();
  f.advance(2500);
  await f.timer();
  assert.equal(frames(f).at(-1).body.at, .5);
  assert.ok([...f.jobs.values()].some(job => job.ms === 1000 / 12));
  f.get('speech-preview').checked = true;
  f.get('speech-preview').onchange();
  await f.timer();
  assert.equal(frames(f).at(-1).body.simulate_speech, true);
  assert.equal(f.get('image-caption').textContent, 'Preview · simulated speech');
});

test('render backpressure retries once and successful recovery clears the visible error', async t => {
  const f = await setup(t);
  f.queue('frame', reply({}, 429), 'POST');
  await f.timer();
  assert.equal(f.get('studio-image').src, undefined);
  await f.timer(1000);
  await f.timer();
  assert.equal(frames(f).length, 2);
  assert.equal(f.get('png').disabled, false);
  f.get('rewind').onclick();
  f.queue('frame', new Error('Failed to fetch'), 'POST');
  await f.timer();
  assert.equal(status(f), 'Connection lost. Retrying the image.');
  await f.timer(1000);
  await f.timer();
  assert.equal(status(f), 'Gesture loaded.');
  assert.equal(f.get('image-caption').textContent, 'Gesture preview · without LCD');
});

test('four failed image reads exhaust the bounded retry budget', async t => {
  const f = await setup(t);
  for (let i = 0; i < 4; i++) f.queue('frame', reply({}, 500), 'POST');
  await f.timer();
  for (let i = 0; i < 3; i++) {
    await f.timer(1000);
    await f.timer();
  }
  assert.equal(frames(f).length, 4);
  assert.equal(status(f), 'Could not read the image. Check time and tempo.');
  assert.equal([...f.jobs.values()].some(job => job.ms === 1000), false);
});

test('live preview handles absent worker and uses runtime-dependent polling without POST', async t => {
  const f = await setup(t);
  await f.timer();
  const old = f.get('studio-image').src;
  f.get('source').value = 'live';
  f.get('source').onchange();
  assert.ok(f.revoked.includes(old));
  f.queue('runtime/frame', reply({}, 404));
  await f.timer();
  assert.equal(f.get('image-caption').textContent, 'The face is not running.');
  assert.equal(f.get('png').disabled, true);
  assert.ok([...f.jobs.values()].some(job => job.ms === 1000));
  f.server.runtime = { running: true, sink: 'file', fps: 12 };
  await f.timer(2000);
  await f.timer(1000);
  await f.timer();
  assert.equal(f.get('image-caption').textContent, 'Image from the active face worker.');
  assert.ok([...f.jobs.values()].some(job => job.ms === 1000 / 12));
  assert.equal(named(f, 'runtime/frame').at(-1).method, 'GET');
  assert.equal(named(f, 'runtime/frame').at(-1).options.body, undefined);
  assert.equal(named(f, 'runtime/play').length, 0);
});

test('invalidated in-flight response cannot replace the image or overlap a newer request', async t => {
  const f = await setup(t);
  const pending = deferred();
  f.queue('frame', () => pending.promise, 'POST');
  const running = f.startTimer();
  await flush();
  const first = frames(f).at(-1);
  f.get('scrub').value = 500;
  f.get('scrub').oninput();
  assert.equal(first.options.signal.aborted, true);
  await f.timer();
  assert.equal(frames(f).length, 1);
  pending.resolve(reply({}));
  await running;
  assert.equal(f.get('studio-image').src, undefined);
  await f.timer();
  assert.equal(frames(f).length, 2);
  assert.equal(frames(f).at(-1).body.at, .5);
  assert.equal(f.get('studio-image').src, 'blob:fixture/0');
});

test('hidden tabs discard delayed blobs and resume both preview and runtime polling', async t => {
  const f = await setup(t);
  const pending = deferred();
  f.queue('frame', reply({}, 200, { blob: () => pending.promise }), 'POST');
  const running = f.startTimer();
  await flush();
  const request = frames(f).at(-1);
  await f.hide();
  assert.equal(request.options.signal.aborted, true);
  pending.resolve(new Blob(['late']));
  await running;
  assert.equal(f.get('studio-image').src, undefined);
  assert.equal(f.jobs.size, 0);
  const previous = named(f, 'runtime').length;
  f.document.hidden = false;
  f.events.get('visibilitychange')();
  await flush();
  assert.equal(named(f, 'runtime').length, previous + 1);
  await f.timer();
  assert.equal(f.get('png').disabled, false);
});

test('aborted frame is silent and hidden startup never starts timers or reads runtime', async t => {
  const f = await setup(t);
  const pending = deferred();
  f.queue('frame', row => {
    row.options.signal.addEventListener('abort', () => pending.reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    return pending.promise;
  }, 'POST');
  const before = status(f);
  const running = f.startTimer();
  await flush();
  await f.hide();
  await running;
  assert.equal(status(f), before);
  assert.equal(f.jobs.size, 0);
  const g = await setup(t, { hidden: true, gestures: [] });
  assert.equal(named(g, 'runtime').length, 0);
  assert.equal(g.jobs.size, 0);
  g.get('play').onclick();
  assert.equal(writes(g).length, 0);
});

test('external settings poll updates clean controls but preserves unsaved user intent', async t => {
  const f = await setup(t);
  f.server.settings = { ...f.server.settings, style: 'minimal', power_mode: 'cable', active_gestures: [] };
  f.server.revision = 'external';
  await f.timer(2000);
  assert.equal(f.get('style').value, 'minimal');
  assert.equal(f.get('active-gesture').checked, false);
  assert.match(f.get('runtime-status').textContent, /Face stopped.*cable/);
  f.get('intensity').value = 75;
  f.get('intensity').oninput();
  f.server.settings = { ...f.server.settings, intensity: .25 };
  f.server.revision = 'newer';
  f.server.runtime = { running: true, sink: 'lcd', fps: 15 };
  await f.timer(2000);
  assert.equal(f.get('intensity').value, '75');
  assert.equal(f.get('runtime-status').textContent, 'Face running · lcd · 15 FPS');
  await f.get('reload-settings').onclick();
  assert.equal(f.get('intensity').value, '25');
  assert.equal(f.get('settings-status').textContent, 'Settings saved on this robot.');
  f.server.runtime = { error: 'lcd_owned_or_unknown' };
  await f.timer(2000);
  assert.equal(f.get('runtime-status').textContent, 'LCD is used by another feature.');
  f.queue('runtime', new Error('runtime disconnected'));
  await f.timer(2000);
  assert.equal(f.get('runtime-status').textContent, 'runtime disconnected');
});

test('settings controls add and remove active gestures and apply the exact typed snapshot', async t => {
  const f = await setup(t);
  f.select();
  f.get('active-gesture').checked = true;
  f.get('active-gesture').onchange();
  f.get('active-gesture').checked = false;
  f.get('active-gesture').onchange();
  f.get('power-mode').value = 'cable';
  f.get('power-mode').onchange();
  f.get('idle').checked = false;
  f.get('idle').onchange();
  f.get('tempo').value = 200;
  f.get('tempo').oninput();
  f.get('transition').value = 'in_out';
  f.get('transition').onchange();
  await f.get('apply').onclick();
  const saved = writes(f).at(-1);
  assert.equal(saved.path, 'runtime');
  assert.equal(saved.body.tempo, 2);
  assert.equal(saved.body.idle, false);
  assert.equal(saved.body.power_mode, 'cable');
  assert.equal(saved.body.transition, 'in_out');
  assert.deepEqual(saved.body.active_gestures, ['builtin:happy']);
  assert.equal(saved.body.if_revision, 'first');
  assert.match(status(f), /Settings saved.*LCD was not started/);
  assert.equal(named(f, 'runtime/play').length, 0);
});

for (const [action, path, method] of [
  ['reload-settings', 'runtime', 'GET'],
  ['lcd-play', 'runtime/play', 'POST'],
  ['lcd-stop', 'runtime/stop', 'POST'],
]) test(action + ' failure is handled and visible', async t => {
  const f = await setup(t);
  f.queue(path, reply({ error: 'lcd_unavailable' }, 503), method);
  await f.get(action).onclick();
  assert.equal(status(f), 'LCD is unavailable on this device.');
});

test('explicit LCD play and stop retain payload and immediate poll ordering', async t => {
  const f = await setup(t);
  const count = f.calls.length;
  await f.get('lcd-play').onclick();
  await flush();
  const play = f.calls[count];
  assert.equal(play.path, 'runtime/play');
  assert.deepEqual(play.body, { sink: 'lcd', gesture_id: 'builtin:happy', expr: 'happy' });
  assert.equal(f.calls[count + 1].path, 'runtime');
  const stopIndex = f.calls.length;
  await f.get('lcd-stop').onclick();
  await flush();
  assert.equal(f.calls[stopIndex].path, 'runtime/stop');
  assert.deepEqual(f.calls[stopIndex].body, {});
  assert.equal(f.calls[stopIndex + 1].path, 'runtime');
  assert.ok([...f.jobs.values()].some(job => job.ms === 2000));
});

test('language refresh preserves selections and beforeunload only prompts for unsaved intent', async t => {
  const label = { dataset: { pl: 'Etykieta', en: 'Label' }, textContent: '' };
  const f = await setup(t, { labels: [label] });
  f.get('skin').value = 'cat';
  f.document.documentElement.lang = 'pl-PL';
  f.events.get('dashboard:langchange')();
  assert.equal(label.textContent, 'Etykieta');
  assert.equal(f.get('skin').value, 'cat');
  assert.equal(f.get('skin').children[1].text, 'Kotek');
  assert.equal(f.get('pose-head').children[0].children[4].textContent, 'Przejście');
  let prevented = 0;
  const clean = { preventDefault() { prevented++; }, returnValue: 'unchanged' };
  f.events.get('beforeunload')(clean);
  assert.equal(prevented, 0);
  assert.equal(clean.returnValue, 'unchanged');
  f.get('copy').onclick();
  const dirty = { preventDefault() { prevented++; }, returnValue: 'unchanged' };
  f.events.get('beforeunload')(dirty);
  assert.equal(prevented, 1);
  assert.equal(dirty.returnValue, '');
});

test('language event before metadata readiness and settings-only unload are safe', async t => {
  const f = faceFixture();
  t.after(() => f.hide());
  f.events.get('dashboard:langchange')();
  await f.ready();
  f.get('idle').onchange();
  let prevented = false;
  const event = { preventDefault() { prevented = true; }, returnValue: 'original' };
  f.events.get('beforeunload')(event);
  assert.equal(prevented, true);
  assert.equal(event.returnValue, '');
});
