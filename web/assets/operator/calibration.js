import { request, poll } from './transport.js';
import { nowSeconds, commandSeconds } from './model.js';
import { el, text, tr, kv, button, ageLabel, showError } from './ui.js';
import { MAX_PROFILE_BYTES, digestValid, defaultProfile, measuredTable, profileError,
  parseImportedProfile, trialAverage, activationAllowed, activationView, pulseValues, referenceConfirmed, freshCalibration, activationPendingResult, sdkOutputObservation, sensorObservations, currentDynamics } from './calibration-model.js';

const byId = id => document.getElementById(id);
const conditions = [['firmware', 'Firmware', 'Firmware'], ['surface', 'Podłoże', 'Surface'],
  ['load', 'Obciążenie', 'Load'], ['battery', 'Bateria / stan zasilania', 'Battery / power state'],
  ['power_cable', 'Kabel i sposób zasilania', 'Cable and power setup'], ['commit', 'Commit oprogramowania', 'Software commit'],
  ['operator', 'Operator pomiarów', 'Measurement operator'], ['date', 'Data pomiarów', 'Measurement date']];
const observations = [['minimum_steps', 'Minimalne SDK step — jazda / skręt', 'Minimum SDK steps — linear / turn'],
  ['acceleration', 'Przyspieszanie — pomiar / faza / jednostka', 'Acceleration — measurement / phase / unit'],
  ['deceleration', 'Hamowanie — pomiar / faza / jednostka', 'Deceleration — measurement / phase / unit'],
  ['reversal', 'Zmiana kierunku — pomiar / jednostka', 'Reversal — measurement / unit'],
  ['stop_distance', 'Droga zatrzymania (m) / dowody', 'Stopping distance (m) / evidence'],
  ['stop_delay', 'Opóźnienie zatrzymania (s) / dowody', 'Stopping delay (s) / evidence'],
  ['position_error', 'Błąd pozycji (m) / dowody', 'Position error (m) / evidence'],
  ['heading_error', 'Błąd kierunku (rad) / dowody', 'Heading error (rad) / evidence'],
  ['battery_policy', 'Warunki baterii i ograniczenia', 'Battery conditions and limits'],
  ['tilt_policy', 'Przechył i ograniczenia', 'Tilt and limits']];
const observationText = value => value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const number = id => { const value = byId(id).value.trim(); return value ? Number(value) : NaN; };
function field(id, pl, en, type = 'text', options = null) {
  const label = el('label'), caption = el('span', '', tr(pl, en));
  caption.dataset.pl = pl; caption.dataset.en = en;
  const input = el(options ? 'select' : 'input'); if (id) input.id = id;
  if (options) for (const [value, titlePl, titleEn] of options) {
    const option = el('option', '', tr(titlePl, titleEn)); option.value = value;
    option.dataset.pl = titlePl; option.dataset.en = titleEn; input.append(option);
  } else { input.type = type; input.maxLength = 500; if (type === 'number') input.step = 'any'; }
  label.append(caption, input); return label;
}
export class Calibration {
  constructor(safety) {
    this.safety = safety; this.state = null; this.profile = defaultProfile(); this.measurements = [];
    this.busy = false; this.dirty = false; this.loadedDigest = null; this.awaiting = null; this.referencePending = null; this.records = [];
    byId('calibration-conditions').append(...conditions.map(([key, pl, en]) => field('condition-' + key, pl, en)));
    byId('calibration-physical-observations').append(...observations.map(([key, pl, en]) => field('observation-' + key, pl, en)));
    this.observationFields(); this.loadProfile(this.profile);
    const act = (id, event, callback) => byId(id).addEventListener(event, value => {
      value.preventDefault(); Promise.resolve().then(callback).catch(showError);
    });
    act('calibration-profile-form', 'submit', () => this.save());
    act('new-calibration-profile', 'click', () => this.loadProfile(defaultProfile(this.state?.motion?.dynamics)));
    act('add-linear-rate', 'click', () => this.addRate('linear'));
    act('add-turn-rate', 'click', () => this.addRate('turn'));
    act('calibration-observation-form', 'submit', () => this.addObservation());
    act('refresh-calibration-history', 'click', () => this.loadCatalog());
    act('load-calibration-revision', 'click', () => this.loadRevision());
    act('export-calibration-revision', 'click', () => this.exportRevision());
    act('import-calibration-file', 'change', () => this.importFile());
    act('calibration-activate-form', 'submit', () => this.activate());
    act('calibration-pulse-form', 'submit', () => this.pulse());
    act('calibration-reference-form', 'submit', () => this.reference());
    byId('calibration-profile-form').addEventListener('input', event => {
      this.dirty = true;
      if (event.target.id !== 'measurements-confirmed') byId('measurements-confirmed').checked = false;
    });
    byId('calibration-revision').addEventListener('change', () => {
      byId('calibration-activation-consent').checked = false; this.render();
    });
    this.loadCatalog().catch(showError);
    this.poller = poll(() => this.load(), { interval: 2000, onError: error => {
      this.state = null; this.render(); showError(error);
    } });
    window.addEventListener('pagehide', () => this.poller.stop());
    window.addEventListener('dashboard:langchange', () => { this.render(); this.renderObservations(); });
  }
  observationFields() {
    const node = byId('calibration-observation-fields');
    node.append(field('trial-kind', 'Rodzaj', 'Kind', '', [['linear', 'Jazda', 'Linear'], ['turn', 'Skręt', 'Turn']]),
      field('trial-step', 'Signed SDK step (nie wartość panelu)', 'Signed SDK step (not panel value)', 'number'),
      field('trial-duration', 'Zmierzony czas (s)', 'Measured duration (s)', 'number'),
      field('trial-distance', 'Podpisany dystans (m)', 'Signed distance (m)', 'number'),
      field('trial-angle', 'Podpisany kąt (rad)', 'Signed angle (rad)', 'number'),
      field('trial-phase', 'Faza pomiaru', 'Measurement phase', '', [
        ['complete', 'Cała próba — średnia z rampą', 'Whole trial — average with ramp'],
        ['acceleration', 'Przyspieszanie', 'Acceleration'], ['steady', 'Ruch ustalony', 'Steady motion'],
        ['deceleration', 'Hamowanie', 'Deceleration']]),
      field('trial-status', 'Wynik obserwacji operatora', 'Operator observation result', '', [
        ['failed', 'Nieudana / niepotwierdzona', 'Failed / unconfirmed'], ['passed', 'Pomiar wykonany', 'Measurement recorded']]),
      field('trial-notes', 'Notatki i dowody próby', 'Trial notes and evidence'));
  }
  async load() {
    this.state = (await request('/api/calibration/state')).data;
    if (this.state?.motion?.contract_version === 1 && freshCalibration(this.state.motion, nowSeconds())
      && (!this.safety.state || this.state.motion.observed_at >= this.safety.state.observed_at)) this.safety.update(this.state.motion);
    if (!this.dirty && !this.loadedDigest && !this.profile.name) {
      for (const key of ['speed_limit', 'linear_rate', 'turn_rate']) {
        const value = this.state?.motion?.dynamics?.[key];
        if (Number.isFinite(value) && value > 0) byId('motion-' + key.replaceAll('_', '-')).value = value;
      }
    }
    this.render();
  }
  async loadCatalog() {
    try {
      const result = await request('/api/calibration/profiles');
      if (result.data.schema_version !== 1 || !Array.isArray(result.data.profiles)) throw new Error('profile_catalog_invalid');
      this.records = result.data.profiles.filter(row => digestValid(row.digest)).slice(0, 64);
      const selected = byId('calibration-revision').value, select = byId('calibration-revision');
      select.replaceChildren(el('option', '', '—'));
      for (const row of this.records) {
        const option = el('option', '', row.name + ' · ' + (row.provenance?.kind || '?') + ' · ' + row.digest.slice(0, 12));
        option.value = row.digest; select.append(option);
      }
      select.value = this.records.some(row => row.digest === selected) ? selected : '';
      text('calibration-profile-history-status', this.records.length + ' · ' + tr('zapamiętana lista rewizji — odśwież na żądanie', 'cached revision list — refresh on request'));
    } catch (error) { text('calibration-profile-history-status', 'unknown · ' + error.message); throw error; }
    finally { this.render(); }
  }
  loadProfile(profile, digest = null) {
    this.profile = structuredClone(profile); this.loadedDigest = digest;
    this.measurements = structuredClone(profile.measurements || []); this.dirty = false;
    const values = { 'profile-name': profile.name, 'profile-kind': profile.provenance.kind,
      'profile-notes': profile.provenance.notes, 'measurement-id': profile.odometry.measurement_id,
      'imu-yaw-sign': profile.odometry.imu_yaw_sign ?? '', 'motion-speed-limit': profile.motion.speed_limit,
      'motion-linear-rate': profile.motion.linear_rate, 'motion-turn-rate': profile.motion.turn_rate };
    for (const [id, value] of Object.entries(values)) byId(id).value = value ?? '';
    for (const [key] of conditions) byId('condition-' + key).value = profile.odometry.conditions?.[key] ?? '';
    for (const [key] of observations) byId('observation-' + key).value = observationText(profile.odometry.observations?.[key]);
    const extras = Object.keys(profile.odometry.conditions || {}).filter(key => !conditions.some(row => row[0] === key))
      .concat(Object.keys(profile.odometry.observations || {}).filter(key => !observations.some(row => row[0] === key)));
    text('calibration-extra-evidence', extras.length ? tr('Dodatkowe zachowane pola', 'Additional preserved fields') + ': ' + extras.join(', ') : '');
    for (const kind of ['linear', 'turn']) {
      byId('calibration-' + kind + '-table').replaceChildren();
      for (const [step, rate] of Object.entries(profile.odometry[kind === 'linear' ? 'linear_m_s' : 'turn_rad_s'] || {})) {
        this.addRate(kind, step, rate, false);
      }
    }
    byId('measurements-confirmed').checked = false; byId('calibration-activation-consent').checked = false;
    text('calibration-loaded', digest ? tr('Wczytano rewizję', 'Loaded revision') + ': ' + digest
      : tr('Nowy / zaimportowany szkic — bez aktywacji', 'New / imported draft — not activated'));
    this.renderObservations(); this.render();
  }
  addRate(kind, step = '', rate = '', edited = true) {
    const target = byId('calibration-' + kind + '-table');
    if (target.children.length >= (kind === 'linear' ? 24 : 140)) throw new Error('measurement_table_limit');
    const row = el('div', 'calibration-rate-row');
    const stepField = field('', 'Signed SDK step', 'Signed SDK step', 'number');
    const rateField = field('', kind === 'linear' ? 'Prędkość (m/s)' : 'Prędkość (rad/s)',
      kind === 'linear' ? 'Rate (m/s)' : 'Rate (rad/s)', 'number');
    const inputs = [stepField.querySelector('input'), rateField.querySelector('input')];
    inputs[0].dataset.step = ''; inputs[0].value = step;
    inputs[1].dataset.rate = ''; inputs[1].value = rate;
    row.append(stepField, rateField, button(tr('Usuń wpis', 'Remove row'), () => {
      row.remove(); this.dirty = true; byId('measurements-confirmed').checked = false;
    }));
    target.append(row);
    if (edited) { this.dirty = true; byId('measurements-confirmed').checked = false; }
  }
  currentConditions() { return { ...(this.profile?.odometry?.conditions || {}), ...Object.fromEntries(conditions.map(([key]) => [key, byId('condition-' + key).value.trim()])) }; }
  buildProfile() {
    const table = kind => measuredTable([...byId('calibration-' + kind + '-table').children].map(row => ({
      step: row.querySelector('[data-step]').value, rate: row.querySelector('[data-rate]').value,
    })), kind === 'linear' ? 12 : 70);
    const kind = byId('profile-kind').value;
    return { schema_version: 1, name: byId('profile-name').value.trim(),
      provenance: { kind, notes: byId('profile-notes').value.trim() },
      motion: { speed_limit: number('motion-speed-limit'), linear_rate: number('motion-linear-rate'),
        turn_rate: number('motion-turn-rate') },
      odometry: { schema_version: 1, manual_verified: kind === 'manual' && byId('measurements-confirmed').checked === true,
        measurement_id: byId('measurement-id').value.trim(),
        imu_yaw_sign: [-1, 1].includes(number('imu-yaw-sign')) ? number('imu-yaw-sign') : null,
        observations: { ...(this.profile.odometry.observations || {}), ...Object.fromEntries(observations.map(([key]) => {
          const value = byId('observation-' + key).value.trim(), original = this.profile.odometry.observations?.[key];
          return [key, value === observationText(original) ? structuredClone(original ?? null) : value || null];
        })) },
        conditions: this.currentConditions(), linear_m_s: table('linear'), turn_rad_s: table('turn') },
      measurements: structuredClone(this.measurements) };
  }
  async save() {
    if (this.busy) return;
    const profile = this.buildProfile(), error = profileError(profile);
    if (error) throw new Error(error);
    if (new TextEncoder().encode(JSON.stringify(profile)).length > MAX_PROFILE_BYTES) throw new Error('profile_too_large');
    this.busy = true; this.render();
    try {
      const result = await request('/api/calibration/profiles', { method: 'POST', body: { profile, imported: false } });
      if (!digestValid(result.data.digest) || !result.data.profile) throw new Error('saved_profile_confirmation_missing');
      this.loadProfile(result.data.profile, result.data.digest);
      await this.loadCatalog(); byId('calibration-revision').value = result.data.digest; this.render();
      text('operator-message', tr('Rewizja zapisana. Nic nie aktywowano ani nie uruchomiono.', 'Revision saved. Nothing activated or started.'));
    } finally { this.busy = false; this.render(); }
  }
  addObservation() {
    if (this.measurements.length >= 128) throw new Error('trial_record_limit');
    const kind = byId('trial-kind').value, step = number('trial-step'), duration = number('trial-duration');
    const distance = byId('trial-distance').value.trim() ? number('trial-distance') : null;
    const angle = byId('trial-angle').value.trim() ? number('trial-angle') : null;
    if (!Number.isInteger(step) || step === 0 || Math.abs(step) > (kind === 'linear' ? 12 : 70) || (kind === 'turn' && Math.abs(step) < 20)
      || !Number.isFinite(duration) || duration <= 0
      || [distance, angle].some(value => value !== null && !Number.isFinite(value))) throw new Error('invalid_trial_observation');
    const row = { measurement_id: byId('measurement-id').value.trim(), kind, sdk_step: step, duration_s: duration,
      distance_m: distance, angle_rad: angle, phase: byId('trial-phase').value, status: byId('trial-status').value,
      notes: byId('trial-notes').value.trim(), conditions: this.currentConditions() };
    this.measurements.push(row); this.dirty = true; byId('measurements-confirmed').checked = false;
    this.renderObservations();
  }
  renderObservations() {
    const table = el('table', 'calibration-table'), head = el('tr');
    for (const title of [tr('Próba / faza', 'Trial / phase'), tr('Pomiar', 'Measurement'),
      tr('Średnia (nie wpis tabeli)', 'Average (not a table entry)'), tr('Wynik / dowody', 'Result / evidence'), '']) head.append(el('th', '', title));
    const thead = el('thead'); thead.append(head); const body = el('tbody');
    this.measurements.forEach((row, index) => {
      const node = el('tr'), avg = trialAverage(row);
      const values = [(row.kind || '?') + ' · step ' + (row.sdk_step ?? '?') + ' · ' + (row.phase || '?'),
        (row.duration_s ?? '—') + ' s · ' + (row.distance_m ?? '—') + ' m · ' + (row.angle_rad ?? '—') + ' rad',
        avg === null ? 'unknown' : avg.toFixed(4) + (row.kind === 'linear' ? ' m/s' : ' rad/s'),
        (row.status || '?') + ' · ' + (row.notes || '—')];
      node.append(...values.map(value => el('td', '', value)));
      const remove = el('td'); remove.append(button(tr('Usuń', 'Remove'), () => {
        this.measurements.splice(index, 1); this.dirty = true; byId('measurements-confirmed').checked = false; this.renderObservations();
      })); node.append(remove); body.append(node);
    });
    table.append(thead, body); byId('calibration-observations').replaceChildren(table);
  }
  selectedDigest() {
    const value = byId('calibration-revision').value;
    if (!digestValid(value)) throw new Error('select_saved_revision');
    return value;
  }
  async revision() {
    const digest = this.selectedDigest(), result = await request('/api/calibration/profiles/' + digest);
    if (result.data.digest !== digest || profileError(result.data.profile)) throw new Error('profile_revision_invalid');
    return result.data;
  }
  async loadRevision() { const value = await this.revision(); this.loadProfile(value.profile, value.digest); }
  async exportRevision() {
    const value = await this.revision(), blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' });
    const link = el('a'); link.href = URL.createObjectURL(blob); link.download = 'rider-calibration-' + value.digest + '.json';
    link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }
  async importFile() {
    const input = byId('import-calibration-file'), file = input.files?.[0]; input.value = '';
    if (!file) return;
    if (file.size > MAX_PROFILE_BYTES) throw new Error('profile_too_large');
    const profile = parseImportedProfile(await file.text()); this.loadProfile(profile); this.dirty = true;
    text('operator-message', tr('Import jest historyczny i niezweryfikowany. Zapisz rewizję; aktywacja jest osobna.',
      'Import is historical and unverified. Save a revision; activation is separate.'));
  }
  async activate() {
    if (this.busy || this.awaiting) return;
    const digest = this.selectedDigest(), plan = byId('calibration-activation-plan').value.trim();
    if (!byId('calibration-activation-consent').checked || !plan) throw new Error('explicit_configuration_consent_required');
    if (!activationAllowed(this.state, this.safety.state, this.safety.clockFresh(), nowSeconds())) throw new Error('fresh_disarmed_configuration_state_required');
    const command = { profile_digest: digest, generation: this.safety.state.generation, seq: ++this.safety.seq,
      source: 'manual', ts: commandSeconds(), ttl_ms: 500,
      request_id: globalThis.crypto?.randomUUID?.() || 'calibration-' + Date.now() + '-' + Math.random().toString(16).slice(2),
      operator_consent: true, operator_plan: plan };
    byId('calibration-activation-consent').checked = false;
    this.busy = true; this.awaiting = command; this.render();
    try {
      await request('/api/calibration/activate', { method: 'POST', body: command });
      text('calibration-activation-result', tr('Żądanie wysłane; oczekiwanie na odczyt obu modułów.', 'Request sent; waiting for both consumers to be observed.'));
    } catch (error) {
      this.awaiting = null; throw error;
    } finally { this.busy = false; this.poller.refresh(); this.render(); }
  }
  async pulse() {
    if (this.busy) return;
    const consent = byId('pulse-consent').checked, plan = byId('pulse-plan').value.trim();
    byId('pulse-consent').checked = false;
    if (!consent || !plan) throw new Error('explicit_single_trial_consent_required');
    const values = pulseValues(byId('pulse-vx').value, byId('pulse-yaw').value, byId('pulse-duration').value);
    if (!this.safety.can('manual', 'move') || (values.yaw !== 0 && !this.safety.can('manual', 'turn'))) throw new Error('manual_trial_gate_not_ready');
    this.busy = true; this.render();
    try {
      const response = await this.safety.send('move', { ...values, operator_consent: true, operator_plan: plan });
      text('calibration-pulse-result', (response.pending ? 'pending' : tr('Odpowiedź odebrana — zobacz ACK', 'Response received — inspect ACK'))
        + ' · ' + tr('fizyczne zakończenie niepotwierdzone', 'physical completion unverified'));
    } finally { this.busy = false; this.render(); }
  }
  referenceAllowed() {
    return activationAllowed(this.state, this.safety.state, this.safety.clockFresh(), nowSeconds())
      && this.safety.state.ready === true && this.safety.state.hardware_ready === true
      && (!this.state.active || activationView(this.state, null, nowSeconds()).applied);
  }
  async reference() {
    if (this.busy || this.referencePending) return;
    const consent = byId('reference-consent').checked, plan = byId('reference-plan').value.trim();
    byId('reference-consent').checked = false;
    if (!consent || !plan) throw new Error('explicit_reference_consent_required');
    if (!this.referenceAllowed()) throw new Error('fresh_disarmed_reference_state_required');
    const home = byId('reference-home-confirmed').checked;
    const coordinates = { x: number('reference-x'), y: number('reference-y'), theta: number('reference-theta') };
    if (!Object.values(coordinates).every(Number.isFinite)
      || (home && !['reference-home-x', 'reference-home-y'].every(id => Number.isFinite(number(id))))) throw new Error('measured_reference_coordinates_required');
    const command = { ...coordinates, home_operator_confirmed: home,
      ...(this.state.active ? { profile_digest: this.state.active.profile_digest } : {}),
      ...(home ? { home_x: number('reference-home-x'), home_y: number('reference-home-y') } : {}),
      generation: this.safety.state.generation, seq: ++this.safety.seq, source: 'manual',
      ts: commandSeconds(), ttl_ms: 500,
      request_id: globalThis.crypto?.randomUUID?.() || 'reference-' + Date.now() + '-' + Math.random().toString(16).slice(2),
      operator_consent: true, operator_plan: plan };
    this.referencePending = command; this.busy = true; this.render();
    try {
      await request('/api/odometry/reference', { method: 'POST', body: command });
      text('calibration-reference-result', tr('pending — wymagany zgodny ACK i odczyt odniesienia', 'pending — matching ACK and reference observation required'));
    } catch (error) { this.referencePending = null; throw error; }
    finally { this.busy = false; this.poller.refresh(); this.render(); }
  }
  render() {
    const snapshot = this.state?.odometry;
    if (this.referencePending && referenceConfirmed(snapshot, this.referencePending, nowSeconds())) {
      text('calibration-reference-result', tr('Odniesienie zgłoszone przez operatora przyjęte — bez ruchu', 'Operator-reported reference accepted — no motion'));
      this.referencePending = null;
    } else if (this.referencePending && snapshot?.last_ack?.request_id === this.referencePending.request_id
      && snapshot.last_ack.status === 'rejected') {
      text('calibration-reference-result', 'rejected · ' + (snapshot.last_ack.error || 'reference_denied'));
      this.referencePending = null;
    }
    text('calibration-reference-state', freshCalibration(snapshot, nowSeconds()) && !snapshot.error && snapshot?.reference_verified === true
      ? (snapshot.reference_id || 'unknown') + ' · HOME ' + (snapshot.home?.operator_confirmed === true
        ? JSON.stringify([snapshot.home.x, snapshot.home.y]) : 'unknown')
      : tr('Brak bieżącego potwierdzonego odniesienia / HOME', 'No current confirmed reference / HOME'));
    byId('calibration-reference').disabled = this.busy || Boolean(this.referencePending) || !this.referenceAllowed();
    if (this.referencePending && nowSeconds() - this.referencePending.ts > 8) {
      text('calibration-reference-result', tr('unknown — brak zgodnego ACK; bez ponowienia', 'unknown — no matching ACK; no retry'));
      this.referencePending = null;
    }
    const state = this.state, view = activationView(state, this.awaiting?.profile_digest, nowSeconds());
    if (this.awaiting) {
      const result = activationPendingResult(state, this.awaiting, nowSeconds());
      if (result) {
        text('calibration-activation-result', result.status === 'applied'
          ? tr('Oba moduły przyjęły konfigurację', 'Both consumers accepted configuration') + ' · ' + this.awaiting.profile_digest
          : result.status + ' · ' + result.reason + ' · ' + this.awaiting.request_id);
        this.awaiting = null;
      }
    }
    text('calibration-runtime-status', view.applied
      ? tr('Konfiguracja przyjęta przez oba moduły', 'Configuration accepted by both consumers') + ' · ' + view.confirmation
      : (state?.status === 'unconfigured' ? tr('Brak aktywnego profilu', 'No active profile') : view.status)
        + ' · ' + (state?.error || tr('wymagany odczyt obu modułów', 'both consumer observations required')));
    const rows = [];
    for (const [name, row] of [['motion', state?.motion?.calibration], ['odometry', state?.odometry?.calibration]]) {
      rows.push([name, (row?.profile_digest || 'unknown') + ' · ' + (row?.source || 'unknown') + ' · ' + ageLabel(row)
        + (row?.error ? ' · ' + row.error : '')]);
    }
    rows.push([tr('Pomiary w profilu', 'Profile measurements'), view.recordVerified
      ? tr('jawnie zweryfikowany zapis operatora', 'explicitly verified operator record')
      : tr('szkic / historyczne / niezweryfikowane', 'draft / historical / unverified')]);
    rows.push([tr('Model odometrii', 'Odometry model'), view.modelReady
      ? tr('bieżący model gotowy — dead reckoning, nie pomiar lokalizacji', 'current model ready — dead reckoning, not measured localization')
      : tr('niegotowy / niezweryfikowany', 'unready / unverified') + ' · ' + (view.modelError || 'unknown')]);
    rows.push([tr('Wykonanie fizyczne', 'Physical completion'), 'unverified']);
    byId('calibration-runtime').replaceChildren(kv(rows));
    const motion = state?.motion, at = nowSeconds(), sdk = sdkOutputObservation(motion, at);
    const sensors = sensorObservations(motion, at), dynamics = currentDynamics(motion, at);
    const age = value => value === null ? tr('wiek nieznany', 'age unknown') : value.toFixed(2) + ' s';
    const timestamp = value => typeof value === 'number' && Number.isFinite(value) ? String(value) : 'unknown';
    const liveRows = [[tr('Sprzęt wykonawcy: gotowość / błąd', 'Executor hardware: readiness / error'),
      (freshCalibration(motion, at) && typeof motion?.hardware_ready === 'boolean' ? String(motion.hardware_ready) : 'unknown')
        + ' · ' + (motion?.error || '—') + ' · ' + ageLabel(motion)],
      [tr('Signed SDK steps: jazda / skręt', 'Signed SDK steps: linear / turn'),
      (sdk.linear_step === null ? 'unknown' : String(sdk.linear_step)) + ' / '
        + (sdk.turn_step === null ? 'unknown' : String(sdk.turn_step)) + ' · ' + sdk.status + ' · ' + age(sdk.age_s)
        + (sdk.status === 'stale' ? ' · ' + tr('historia; bieżący ruch niepotwierdzony', 'history; current motion unconfirmed') : '')],
      [tr('Zapis SDK: accepted / źródło / czas', 'SDK write: accepted / source / time'),
        String(sdk.accepted) + ' · ' + (sdk.source || 'unknown') + ' · observed_at ' + timestamp(sdk.observed_at)],
      [tr('Zapis SDK: instancja / generacja', 'SDK write: instance / generation'),
        (sdk.instance_id || 'unknown') + ' · ' + (sdk.generation || 'unknown') + (sdk.error ? ' · ' + sdk.error : '')]];
    for (const [name, row] of Object.entries(sensors)) {
      liveRows.push([name === 'battery' ? tr('Bateria (%)', 'Battery (%)') : 'IMU ' + name + ' · ' + tr('surowa wartość SDK', 'raw SDK value'),
        (row.value === null ? 'unknown' : String(row.value)) + ' · ' + row.status + ' · '
          + tr('ready', 'ready') + '=' + String(row.ready) + ' · ' + age(row.age_s)
          + ' · observed_at ' + timestamp(row.observed_at) + (row.error ? ' · ' + row.error : '')]);
    }
    for (const [key, title] of [['speed_limit', tr('Bieżący limit (0–1)', 'Current limit (0–1)')],
      ['linear_rate', tr('Bieżąca rampa jazdy (znormalizowane/s)', 'Current linear ramp (normalized/s)')],
      ['turn_rate', tr('Bieżąca rampa skrętu (znormalizowane/s)', 'Current turn ramp (normalized/s)')]]) {
      liveRows.push([title, (dynamics[key] === null ? 'unknown' : String(dynamics[key])) + ' · '
        + age(dynamics.age_s) + (dynamics.error ? ' · ' + dynamics.error : '')]);
    }
    liveRows.push([tr('Wykonanie fizyczne', 'Physical completion'), 'unverified']);
    byId('calibration-live-data').replaceChildren(kv(liveRows));
    const ceilings = state?.motion?.calibration?.ceilings;
    text('calibration-ceilings', tr('Pułapy uruchomionego wykonawcy', 'Running executor ceilings') + ': '
      + (ceilings ? JSON.stringify(ceilings) : 'unknown') + ' · ' + tr('nie są pomiarami fizycznymi', 'not physical measurements'));
    const selected = byId('calibration-revision').value;
    text('calibration-activation-target', tr('Wybrany zapisany skrót', 'Selected saved digest') + ': ' + (selected || '—'));
    byId('activate-calibration').disabled = this.busy || Boolean(this.awaiting) || !digestValid(selected)
      || !activationAllowed(state, this.safety.state, this.safety.clockFresh(), nowSeconds());
    byId('save-calibration-profile').disabled = this.busy;
    byId('calibration-pulse').disabled = this.busy || !this.safety.can('manual', 'move');
    if (this.awaiting) text('calibration-activation-result',
      'pending · ' + this.awaiting.request_id + ' · ' + tr('potwierdzenie obu modułów niepełne', 'both consumer confirmations incomplete'));
  }
}
