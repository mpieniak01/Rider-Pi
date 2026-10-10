import { ageOf, authorized, safetyKnown, editingTarget, matchingAck, nowSeconds, commandSeconds, setServerClock } from './model.js';
import { request, poll } from './transport.js';
import { el, text, tr, statusLabel, showError } from './ui.js';
export class SafetyPanel {
  constructor(onChange = () => {}) {
    this.state = null; this.onChange = onChange; this.seq = -1; this.generation = null;
    this.history = []; this.pending = new Map(); this.mutating = false;
    this.revokedGenerations = new Set();
    this.clockReady = false; this.clockObserved = 0;
    this.preparation();
    this.poller = poll(async () => {
      const response = await request('/api/control/state');
      this.clockReady = setServerClock(response.data.server_time, response.sent_at, response.received_at);
      if (this.clockReady) this.clockObserved = Date.now() / 1000;
      this.update(response.data.safety);
    },
      { interval: 1000, onError: error => { this.suspend(); showError(error); } });
    this.expiry = setInterval(() => this.render(), 250);
    document.querySelectorAll('[data-stop]').forEach(node => node.addEventListener('click', () => this.stop()));
    document.getElementById('arm-form')?.addEventListener('submit', event => { event.preventDefault(); this.arm('arm'); });
    document.getElementById('clear-estop')?.addEventListener('click', () => this.arm('clear_estop'));
    document.getElementById('disarm')?.addEventListener('click', () => this.send('disarm', {}, '/api/safety').catch(showError));
    document.getElementById('estop')?.addEventListener('click', () => this.send('estop', {}, '/api/safety').catch(showError));
    document.querySelectorAll('[data-direction]').forEach(node => node.addEventListener('click', () => this.move(node.dataset.direction)));
    document.addEventListener('keydown', event => this.key(event));
    window.addEventListener('blur', () => this.suspend());
    document.addEventListener('visibilitychange', () => { if (document.hidden) this.suspend(); });
    window.addEventListener('pagehide', () => { this.suspend(); clearInterval(this.expiry); this.poller.stop(); });
  }
  preparation() {
    if (document.getElementById('arm-form') || document.body.dataset.page !== 'system') return;
    const card = document.querySelector('.operator-safety'); if (!card) return;
    const translated = (tag, pl, en) => { const node = el(tag, '', tr(pl, en)); node.dataset.pl = pl; node.dataset.en = en; return node; };
    const section = el('details'); section.append(translated('summary', 'Przygotuj zgodę na tym widoku', 'Prepare permission in this view'));
    const form = el('form'); form.id = 'arm-form';
    const owner = el('select'); owner.id = 'control-owner';
    for (const name of ['manual', 'follow_me', 'navigation']) { const option = el('option', '', name); option.value = name; owner.append(option); }
    owner.value = 'manual';
    const lease = el('input'); lease.id = 'lease'; lease.type = 'number'; lease.min = '1'; lease.max = '30'; lease.value = '10'; lease.required = true;
    const plan = el('textarea'); plan.id = 'operator-plan'; plan.required = true; plan.maxLength = 1000;
    const consent = el('input'); consent.id = 'operator-consent'; consent.type = 'checkbox'; consent.required = true;
    for (const [pl, en, field] of [['Właściciel', 'Owner', owner], ['Czas zgody (s, maks. 30)', 'Lease (s, maximum 30)', lease], ['Konkretny plan: przestrzeń, kabel, próba i STOP', 'Specific plan: space, cable, trial and STOP', plan], ['Robot i przestrzeń przygotowane; świadomie udzielam zgody', 'Robot and space prepared; I explicitly grant permission', consent]]) {
      const wrapper = el('label'); wrapper.append(translated('span', pl, en), field); form.append(wrapper);
    }
    const controls = el('div', 'operator-row');
    for (const [id, pl, en] of [['arm', 'ARM', 'ARM'], ['clear-estop', 'Kasuj ESTOP → DISARMED', 'Clear ESTOP → DISARMED'], ['disarm', 'DISARM', 'DISARM'], ['estop', 'ESTOP', 'ESTOP']]) {
      const button = translated('button', pl, en); button.className = 'c-btn'; button.id = id; button.type = id === 'arm' ? 'submit' : 'button'; button.disabled = ['arm', 'clear-estop'].includes(id); controls.append(button);
    }
    form.append(controls); section.append(form); card.append(section);
  }
  revoke() {
    if (this.state?.state !== 'ARMED') return;
    this.revokedGenerations.add(this.state.generation);
    while (this.revokedGenerations.size > 16) this.revokedGenerations.delete(this.revokedGenerations.values().next().value);
  }
  update(state) {
    this.state = state;
    if (this.generation !== state?.generation) { this.generation = state?.generation; this.seq = -1; }
    this.seq = Math.max(this.seq, Number.isInteger(state?.last_seq) ? state.last_seq : -1);
    for (const ack of [...(state?.recent_acks || []), state?.last_ack].filter(Boolean)) this.ack(ack);
    this.render();
  }
  clockFresh() { const age = Date.now() / 1000 - this.clockObserved; return this.clockReady && age >= 0 && age <= 3; }
  can(owner = 'manual', action = 'move') { return this.clockFresh() && !this.revokedGenerations.has(this.state?.generation) && authorized(this.state, owner, action); }
  envelope(action, params = {}, owner = 'manual') {
    if (!safetyKnown(this.state) || !this.clockFresh()) throw new Error(tr('Brak świeżego kontraktu bezpieczeństwa v1 i potwierdzonego zegara', 'No fresh safety contract v1 and confirmed clock'));
    if (!['arm', 'clear_estop'].includes(action) && (!this.can(owner, action) || (action === 'move' && params.yaw && !this.can(owner, 'turn')))) throw new Error(tr('Napęd zablokowany: stan, właściciel lub możliwości', 'Actuator blocked: state, owner or capability'));
    return { ...params, action, source: 'manual', generation: this.state.generation, seq: ++this.seq,
      request_id: globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      ts: commandSeconds(), ttl_ms: 500 };
  }
  async send(action, params = {}, endpoint = '/api/control', owner = 'manual') {
    const exempt = ['stop', 'disarm', 'estop'].includes(action);
    if (['move', 'turn'].includes(action) && (![params.vx, params.yaw, params.duration].every(Number.isFinite)
      || Math.abs(params.vx) > 1 || Math.abs(params.yaw) > 1 || params.duration < .01 || params.duration > .25)) throw new Error(tr('Nieprawidłowy impuls: wartości -1–1, czas 0.01–0.25 s', 'Invalid pulse: values -1–1, duration 0.01–0.25 s'));
    if (action === 'height' && (!Number.isInteger(params.height) || params.height < 0 || params.height > 12)) throw new Error(tr('Wysokość musi być liczbą całkowitą 0–12', 'Height must be an integer 0–12'));
    if (action === 'action' && (!Number.isInteger(params.action_id) || params.action_id < 1 || params.action_id > 255)) throw new Error(tr('ID akcji musi być liczbą całkowitą 1–255', 'Action ID must be an integer 1–255'));
    if (this.mutating && !exempt) throw new Error(tr('Poczekaj na odpowiedź poprzedniego żądania', 'Wait for the previous request'));
    const command = exempt ? { action, source: owner, request_id: `web-${Date.now()}-${Math.random().toString(16).slice(2)}` } : this.envelope(action, params, owner);
    if (exempt) { this.revoke(); this.render(); }
    const submittedAt = commandSeconds();
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
  async arm(action) {
    if (!safetyKnown(this.state) || !this.clockFresh() || this.mutating || this.state.state !== (action === 'arm' ? 'DISARMED' : 'ESTOP')) return;
    if (action === 'arm' && (this.state.ready !== true || this.state.hardware_ready !== true)) return;
    const plan = document.getElementById('operator-plan')?.value.trim();
    const consent = document.getElementById('operator-consent')?.checked === true;
    if (!consent || !plan) return showError(new Error(tr('Podaj konkretny plan i potwierdź przygotowanie robota', 'Enter a specific plan and confirm the robot is prepared')));
    try {
      await this.send(action, { operator_consent: true, operator_plan: plan,
        owner: document.getElementById('control-owner').value, lease_s: Number(document.getElementById('lease').value) }, '/api/safety');
    } catch (error) { showError(error); }
    finally { document.getElementById('operator-consent').checked = false; }
  }
  stop() { this.send('stop').catch(showError); }
  suspend() {
    if (this.state?.state === 'ARMED') {
      this.revoke();
      this.stop();
    }
    this.state = null; this.render();
  }
  move(direction) {
    if (!this.can('manual', direction === 'left' || direction === 'right' ? 'turn' : 'move')) return;
    const speedText = document.getElementById('speed')?.value, yawText = document.getElementById('yaw-speed')?.value, durationText = document.getElementById('duration')?.value;
    const speed = speedText?.trim() ? Number(speedText) : NaN;
    const yaw = yawText?.trim() ? Number(yawText) : NaN;
    const values = { forward: [speed, 0], backward: [-speed, 0], left: [0, -yaw], right: [0, yaw] }[direction];
    if (!values) return;
    this.send('move', { vx: values[0], yaw: values[1], duration: durationText?.trim() ? Number(durationText) : NaN }).catch(showError);
  }
  key(event) {
    if (editingTarget(event.target) || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
    if (event.code === 'Space') { event.preventDefault(); this.stop(); return; }
    if (document.body.dataset.page !== 'control' || !this.can()) return;
    const direction = { KeyW: 'forward', ArrowUp: 'forward', KeyS: 'backward', ArrowDown: 'backward', KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right' }[event.code];
    if (direction) { event.preventDefault(); this.move(direction); }
  }
  render() {
    for (const [id, entry] of this.pending) {
      if (nowSeconds() - entry.submittedAt > 8) {
        entry.status = 'unknown'; entry.reason = 'ack_timeout'; this.pending.delete(id); this.renderHistory();
      }
    }
    const known = safetyKnown(this.state);
    text('safety-state', known ? this.state.state : 'UNKNOWN');
    text('safety-ready', known && this.state.ready === true && this.state.hardware_ready === true ? tr('gotowy wykonawca', 'executor ready') : tr('niepotwierdzona / brak', 'unconfirmed / unavailable'));
    text('safety-age', `${ageOf(this.state)?.toFixed(1) ?? '—'} s`);
    text('safety-owner', known ? this.state.owner || '—' : '—');
    text('safety-reason', this.revokedGenerations.has(this.state?.generation) ? tr('Zgoda lokalnie unieważniona; wymagane STOP i nowe uzbrojenie', 'Permission locally revoked; STOP and new arming required') : !this.clockFresh() ? tr('Zegar serwera niepotwierdzony lub wolne połączenie — tylko odczyt', 'Server clock unconfirmed or slow connection — read only') : known ? this.state.error || this.state.reason || '—' : tr('Brak świeżych danych / stary kontrakt: tylko odczyt', 'Missing fresh data / old contract: read only'));
    text('safety-lease', known && typeof this.state.lease_remaining_s === 'number' ? `${Math.max(0, this.state.lease_remaining_s - Math.max(0, nowSeconds() - this.state.observed_at)).toFixed(1)} s` : '—');
    document.querySelectorAll('[data-direction]').forEach(node => { node.disabled = !this.can('manual', ['left', 'right'].includes(node.dataset.direction) ? 'turn' : 'move') || this.mutating; });
    const arm = document.getElementById('arm'); if (arm) arm.disabled = !known || !this.clockFresh() || this.state.state !== 'DISARMED' || this.state.ready !== true || this.state.hardware_ready !== true || this.mutating;
    const clear = document.getElementById('clear-estop'); if (clear) clear.disabled = !known || !this.clockFresh() || this.state.state !== 'ESTOP' || this.mutating;
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
