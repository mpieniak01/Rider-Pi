import { ageOf, authorized, safetyKnown, editingTarget, matchingAck, setServerClock } from './model.js';
import { request, poll, prepareMutation } from './transport.js';
import { text, tr, statusLabel, showError } from './ui.js';
export class SafetyPanel {
  constructor(onChange = () => {}, { interactive = true } = {}) {
    this.interactive = interactive; this.upperOffset = 0; this.lowerOffset = 0;
    this.lastArmed = false; this.state = null; this.onChange = onChange; this.seq = -1; this.generation = null;
    this.history = []; this.pending = new Map(); this.mutating = false;
    this.revokedGenerations = new Set();
    this.clockReady = false; this.clockObserved = 0;
    this.toggling = false; this.toggleEpoch = 0;
    document.getElementById('global-motion-toggle')?.addEventListener('click', () => this.toggleMotion().catch(showError));
    this.poller = poll(async () => {
      const response = await request('/api/control/state');
      this.clockReady = response.canonical === true && response.meta?.contract_id === 'rider.safety' && response.meta.contract_version === 1 && setServerClock(response.data.server_time, response.sent_at, response.received_at);
      if (this.clockReady) { this.upperOffset = response.data.server_time - response.sent_at; this.lowerOffset = response.data.server_time - response.received_at; }
      if (this.clockReady) this.clockObserved = Date.now() / 1000;
      this.update(response.data.safety);
    },
      { interval: 1000, onError: error => { this.suspend(); showError(error); } });
    this.expiry = setInterval(() => this.render(), 250);
    if (this.interactive) {
      document.querySelectorAll('[data-stop]').forEach(node => node.addEventListener('click', () => this.stop()));
      document.querySelectorAll('[data-direction]').forEach(node => node.addEventListener('click', () => this.move(node.dataset.direction)));
      document.addEventListener('keydown', event => this.key(event));
      window.addEventListener('blur', () => this.suspend());
      document.addEventListener('visibilitychange', () => { if (document.hidden) this.suspend(); });
    }
    window.addEventListener('pagehide', () => { clearInterval(this.expiry); this.poller.stop(); });
  }
  revoke() {
    if (this.state?.state !== 'ARMED') return;
    this.revokedGenerations.add(this.state.generation);
    while (this.revokedGenerations.size > 16) this.revokedGenerations.delete(this.revokedGenerations.values().next().value);
  }
  update(state) {
    if (state) this.lastArmed = state.state === 'ARMED';
    this.state = state;
    if (this.generation !== state?.generation) { this.generation = state?.generation; this.seq = -1; }
    this.seq = Math.max(this.seq, Number.isInteger(state?.last_seq) ? state.last_seq : -1);
    for (const ack of [...(state?.recent_acks || []), state?.last_ack].filter(Boolean)) this.ack(ack);
    this.render();
  }
  controlsActive() { return this.interactive && (document.body.dataset.page !== 'system' || document.getElementById('admin-mode')?.checked === true); }
  now() { return Date.now() / 1000 + this.upperOffset; }
  commandTime() { return Date.now() / 1000 + this.lowerOffset; }
  async prepare() { await prepareMutation(); await this.poller.refresh(); }
  clockFresh() { const age = Date.now() / 1000 - this.clockObserved; return this.clockReady && age >= 0 && age <= 3; }
  can(owner = 'manual', action = 'move') { return (!this.controls || this.controls.ready()) && this.state?.execution_context !== 'test' && this.controlsActive() && this.clockFresh() && !this.revokedGenerations.has(this.state?.generation) && authorized(this.state, owner, action, this.now()); }
  envelope(action, params = {}, owner = 'manual') {
    if (!safetyKnown(this.state, this.now()) || !this.clockFresh()) throw new Error(tr('Brak świeżego kontraktu bezpieczeństwa v1 i potwierdzonego zegara', 'No fresh safety contract v1 and confirmed clock'));
    if (!['arm', 'clear_estop'].includes(action) && (!this.can(owner, action) || (action === 'move' && params.yaw && !this.can(owner, 'turn')))) throw new Error(tr('Napęd zablokowany: stan, właściciel lub możliwości', 'Actuator blocked: state, owner or capability'));
    if (action === 'arm' && this.state.state !== 'DISARMED' || action === 'clear_estop' && this.state.state !== 'ESTOP') throw new Error(tr('Stan zmienił się — sprawdź ponownie zgodę', 'State changed — review permission again'));
    return { ...params, action, source: 'manual', execution_context: 'panel', generation: this.state.generation, seq: ++this.seq,
      request_id: globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      ts: this.commandTime(), ttl_ms: 500 };
  }
  async send(action, params = {}, endpoint = '/api/control', owner = 'manual') {
    if (action === 'move' && this.controls) params = this.controls.pulse(params.direction);
    if (['turn', 'height', 'balance', 'stabilization', 'action'].includes(action) && this.controls) params.settings_revision = this.controls.state?.revision;
    const exempt = ['stop', 'disarm', 'estop'].includes(action);
    if (action === 'arm' && params.arming_mode !== 'operator' && (!Number.isFinite(params.lease_s) || params.lease_s <= 0 || params.lease_s > 30))
      throw new Error('invalid_lease');
    if (['move', 'turn'].includes(action) && params.device_settings !== true && (![params.vx, params.yaw, params.duration].every(Number.isFinite)
      || Math.abs(params.vx) > 1 || Math.abs(params.yaw) > 1 || params.duration < .01 || params.duration > .25)) throw new Error(tr('Nieprawidłowy impuls: wartości -1–1, czas 0.01–0.25 s', 'Invalid pulse: values -1–1, duration 0.01–0.25 s'));
    if (action === 'height' && (!Number.isInteger(params.height) || params.height < 75 || params.height > 115)) throw new Error(tr('Wysokość musi być liczbą całkowitą 75–115', 'Height must be an integer 75–115'));
    if (action === 'action' && (!Number.isInteger(params.action_id) || params.action_id < 1 || params.action_id > 255)) throw new Error(tr('ID akcji musi być liczbą całkowitą 1–255', 'Action ID must be an integer 1–255'));
    if (this.mutating && !exempt) throw new Error(tr('Poczekaj na odpowiedź poprzedniego żądania', 'Wait for the previous request'));
    if (!this.controlsActive() && !['arm', 'clear_estop', 'stop', 'disarm', 'estop'].includes(action)) throw new Error('Motion controls are unavailable on this view');
    if (!exempt) {
      this.mutating = true; this.render();
      try {
        await this.prepare();
        if (action === 'move' && this.controls) {
          await this.controls.refresh();
          const revision = params.settings_revision;
          if (this.controls.state.revision !== revision) throw new Error(tr('Ustawienia zmieniły się — sprawdź wartości i kliknij ponownie.', 'Settings changed — review values and click again.'));
          params = this.controls.pulse(params.direction);
        }
      }
      catch (error) { this.mutating = false; this.render(); throw error; }
    }
    let command;
    try {
      command = exempt ? { action, source: owner, request_id: `web-${Date.now()}-${Math.random().toString(16).slice(2)}` } : this.envelope(action, params, owner);
    } catch (error) { if (!exempt) this.mutating = false; this.render(); throw error; }
    if (exempt) { this.toggleEpoch++; this.revoke(); this.render(); }
    const submittedAt = this.commandTime();
    const entry = { command, submittedAt, status: 'sending' };
    this.history.unshift(entry); this.history = this.history.slice(0, 20); this.pending.set(command.request_id, entry);
    for (const [id, pending] of this.pending) {
      if (!this.history.includes(pending)) this.pending.delete(id);
    }
    if (!exempt) this.mutating = true;
    this.renderHistory();
    try {
      const result = await request(endpoint, { method: 'POST', body: command });
      entry.status = result.status === 202 || result.data.pending ? 'pending' : 'awaiting_ack';
      if (result.data.safety) this.update(result.data.safety);
      if (result.data.ack) this.ack(result.data.ack, result.status === 200 && result.data.confirmed === true && result.data.pending !== true);
      return result.data;
    } catch (error) {
      entry.status = error.status ? 'rejected' : 'unknown'; entry.reason = error.message;
      this.pending.delete(command.request_id); throw error;
    } finally { if (!exempt) this.mutating = false; this.renderHistory(); this.poller.refresh(); }
  }
  ack(ack, confirmedHttp = false) {
    const entry = this.pending.get(ack?.request_id);
    if (!entry || !matchingAck(ack, entry.command, entry.submittedAt, confirmedHttp)) return;
    entry.status = ack.status; entry.ack = ack; entry.reason = ack.reason || ack.error;
    this.pending.delete(ack.request_id); this.renderHistory();
  }
  async toggleMotion() {
    if (this.toggling) return;
    // Disarming/STOP never needs a fresh clock or an authorization envelope.
    if (this.state?.state === 'ARMED' || (!this.state && this.lastArmed)) { await this.send('stop'); return; }
    if (!safetyKnown(this.state, this.now()) || !this.clockFresh()
      || this.state.ready !== true || this.state.hardware_ready !== true) return;
    const epoch = this.toggleEpoch;
    this.toggling = true; this.render();
    const consent = { operator_consent: true, operator_plan: tr(
      'Operator uzbroił robot przyciskiem globalnym; przestrzeń i kabel przygotowane.',
      'Operator armed the robot with the global button; space and cable prepared.'),
      owner: 'manual', arming_mode: 'operator' };
    try {
      if (this.state.state === 'ESTOP') {
        await this.send('clear_estop', consent, '/api/safety');
        await this.poller.refresh();
      }
      // A fresh executor state must confirm clearing; never guess from HTTP acceptance.
      if (epoch !== this.toggleEpoch || !safetyKnown(this.state, this.now()) || !this.clockFresh() || this.state.state !== 'DISARMED')
        throw new Error(tr('Brak potwierdzonego rozbrojenia — uzbrojenie przerwane', 'Disarming unconfirmed — arming cancelled'));
      await this.send('arm', consent, '/api/safety');
    } finally { this.toggling = false; this.render(); }
  }
  renderGlobalToggle() {
    const node = document.getElementById('global-motion-toggle'); if (!node) return;
    const known = safetyKnown(this.state, this.now()) && this.clockFresh();
    const armed = known && this.state.state === 'ARMED' && this.state.can_move === true
      && ((this.state.arming_mode === 'operator' && this.state.execution_context === 'panel' && this.state.owner === 'manual')
        || this.state.lease_remaining_s > ageOf(this.state, this.now()))
      && !this.revokedGenerations.has(this.state.generation);
    const unknownArmed = !this.state && this.lastArmed;
    node.textContent = unknownArmed ? tr('Stan niepotwierdzony — rozbrój', 'State unconfirmed — disarm') : armed ? tr('Robot uzbrojony', 'Robot armed') : tr('Robot rozbrojony', 'Robot disarmed');
    node.classList.toggle('is-armed', armed); node.classList.toggle('is-disarmed', !armed);
    node.setAttribute('aria-pressed', String(armed));
    node.disabled = !unknownArmed && this.state?.state !== 'ARMED' && (this.toggling || this.mutating || (!armed && (!known
      || this.state.ready !== true || this.state.hardware_ready !== true)));
    node.title = (armed || unknownArmed) ? tr('Kliknij, aby zatrzymać i rozbroić. Uzbrojenie trwa do decyzji operatora.',
      'Click to stop and disarm. Arming remains until the operator disarms.') : tr(
      'Kliknięcie zezwala na sterowanie z panelu. Przygotuj przestrzeń i kabel.',
      'Click to permit panel control. Prepare space and cable.');
  }
  stop() { this.send('stop').catch(showError); }
  suspend() {
    // Operator permission survives focus changes and read failures; fresh data
    // still gates every new command. Hardware faults are handled by the executor.
    if (this.state?.arming_mode === 'operator' && this.state?.execution_context === 'panel') {
      this.state = null; this.render(); return;
    }
    if (this.controlsActive() && this.state?.state === 'ARMED') {
      this.revoke();
      this.stop();
    }
    this.state = null; this.render();
  }
  move(direction) {
    if (this.controls) { this.send('move', { direction }).catch(showError); return; }
    if (!this.can('manual', direction === 'left' || direction === 'right' ? 'turn' : 'move')) return;
    const speedText = document.getElementById('speed')?.value, yawText = document.getElementById('yaw-speed')?.value, durationText = document.getElementById('duration')?.value;
    const speed = speedText?.trim() ? Number(speedText) : NaN;
    const yaw = yawText?.trim() ? Number(yawText) : NaN;
    const values = { forward: [speed, 0], backward: [-speed, 0], left: [0, -yaw], right: [0, yaw] }[direction];
    if (!values) return;
    this.send('move', { vx: values[0], yaw: values[1], duration: durationText?.trim() ? Number(durationText) : NaN }).catch(showError);
  }
  key(event) {
    if (!this.controlsActive()) return;
    if (editingTarget(event.target) || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
    if (event.code === 'Space') { event.preventDefault(); this.stop(); return; }
    if (document.body.dataset.page !== 'control' || !this.can()) return;
    const direction = { KeyW: 'forward', ArrowUp: 'forward', KeyS: 'backward', ArrowDown: 'backward', KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right' }[event.code];
    if (direction) { event.preventDefault(); this.move(direction); }
  }
  render() {
    for (const [id, entry] of this.pending) {
      if (this.now() - entry.submittedAt > 8) {
        entry.status = 'unknown'; entry.reason = 'ack_timeout'; this.pending.delete(id); this.renderHistory();
      }
    }
    this.renderGlobalToggle();
    if (!this.interactive) { this.onChange(this.state); return; }
    const known = safetyKnown(this.state, this.now());
    text('safety-state', known ? this.state.state : 'UNKNOWN');
    text('safety-ready', known && this.state.ready === true && this.state.hardware_ready === true ? tr('gotowy wykonawca', 'executor ready') : tr('niepotwierdzona / brak', 'unconfirmed / unavailable'));
    text('safety-age', `${ageOf(this.state, this.now())?.toFixed(1) ?? '—'} s`);
    text('safety-owner', known ? this.state.owner || '—' : '—');
    text('safety-reason', this.revokedGenerations.has(this.state?.generation) ? tr('Zgoda lokalnie unieważniona; wymagane STOP i nowe uzbrojenie', 'Permission locally revoked; STOP and new arming required') : !this.clockFresh() ? tr('Zegar serwera niepotwierdzony lub wolne połączenie — tylko odczyt', 'Server clock unconfirmed or slow connection — read only') : known ? this.state.error || this.state.reason || '—' : tr('Brak świeżych danych / stary kontrakt: tylko odczyt', 'Missing fresh data / old contract: read only'));
    text('safety-lease', known && typeof this.state.lease_remaining_s === 'number' ? `${Math.max(0, this.state.lease_remaining_s - Math.max(0, this.now() - this.state.observed_at)).toFixed(1)} s` : '—');
    document.querySelectorAll('[data-direction]').forEach(node => { node.disabled = !this.can('manual', ['left', 'right'].includes(node.dataset.direction) ? 'turn' : 'move') || this.mutating; });
    this.onChange(this.state);
  }
  renderHistory() {
    const node = document.getElementById('request-history'); if (!node) return;
    node.replaceChildren(...this.history.map(entry => {
      const row = document.createElement('li');
      row.textContent = `${new Date(entry.submittedAt * 1000).toLocaleTimeString()} · ${entry.command.action} · ${statusLabel(entry.status)}${entry.reason ? ` · ${entry.reason}` : ''}${entry.ack?.status === 'executed' ? ` · ${tr('fizyczne zakończenie niepotwierdzone', 'physical completion unverified')}` : ''}`;
      return row;
    }));
  }
}
