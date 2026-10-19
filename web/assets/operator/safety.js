import { requestId } from './request-id.js';
import { HeldMotion } from './held-motion.js?v=motion-descriptors-9';
import { ageOf, authorized, operatorAuthorized, safetyKnown, editingTarget, matchingAck, setServerClock } from './model.js';
import { request, poll, prepareMutation } from './transport.js';
import { text, tr, statusLabel, showError } from './ui.js';
function intentLabel(mode) {
  if(mode==='release')return tr('Wyhamowanie; robot pozostaje uzbrojony.','Decelerating; robot remains armed.');
  if(mode==='hold')return tr('Przytrzymanie — jazda ciągła.','Held — continuous command.');
  return tr('Wysłano impuls.','Pulse sent.');
}
function armingLabel(known,armed,unconfirmed) {
  if(!known)return tr('Stan uzbrojenia nieznany','Arming state unknown');
  const state=armed?tr('Robot uzbrojony','Robot armed'):tr('Robot rozbrojony','Robot disarmed');
  const suffix=unconfirmed?tr(' · ostatni stan',' · last known state'):'';
  return state+suffix;
}
function permissionReason(panel,known) {
  if(panel.revokedGenerations.has(panel.state?.generation))return tr('Zgoda lokalnie unieważniona; wymagane STOP i nowe uzbrojenie','Permission locally revoked; STOP and new arming required');
  if(panel.observationFailed || !known)return tr('Odczyt nieaktualny — pokazano ostatni stan wykonawcy','Observation unavailable — showing last executor state');
  return panel.state.error || panel.state.reason || '—';
}
export class SafetyPanel {
  constructor(onChange = () => {}, { interactive = true } = {}) {
    this.interactive = interactive; this.upperOffset = 0; this.lowerOffset = 0;
    this.lastArmed = false; this.lastConfirmed = null; this.observationFailed = false; this.state = null; this.onChange = onChange; this.seq = -1; this.generation = null;
    this.history = []; this.pending = new Map(); this.mutating = false;
    this.revokedGenerations = new Set();
    this.clockReady = false; this.clockObserved = 0;
    this.held = new HeldMotion({
      send:(intent,valid)=>this.sendIntent(intent,valid),
      modes:()=>this.controls?.state?.control_modes || {},
      allowed:direction=>Boolean(this.controls?.state?.control_modes?.supported?.includes('hold'))
        && this.can('manual',['left','right'].includes(direction)?'turn':'move'),
      error:showError,
      active:direction=>document.querySelectorAll('[data-direction]').forEach(node=>{
        const pressed=node.dataset.direction===direction;
        node.setAttribute('aria-pressed',String(pressed));
        node.classList.toggle('is-held',pressed);
      })
    });
    this.toggling = false; this.toggleEpoch = 0;
    document.getElementById('global-motion-toggle')?.addEventListener('click', () => this.toggleMotion().catch(showError));
    this.poller = poll(async () => {
      const response = await request('/api/control/state');
      const clockReady = response.canonical === true && response.meta?.contract_id === 'rider.safety' && response.meta.contract_version === 1 && setServerClock(response.data.server_time, response.sent_at, response.received_at);
      if (clockReady) {
        this.clockReady = true; this.upperOffset = response.data.server_time - response.sent_at;
        this.lowerOffset = response.data.server_time - response.received_at; this.clockObserved = Date.now() / 1000;
      }
      this.observationFailed = false;
      this.update(response.data.safety);
    },
      { interval: 1000, onError: error => { this.observationFailed = true; this.held.stop(); this.render(); showError(error); } });
    this.expiry = setInterval(() => this.render(), 250);
    if (this.interactive) {
      document.querySelectorAll('[data-stop]').forEach(node => node.addEventListener('click', () => this.stop()));
      document.querySelectorAll('[data-direction]').forEach(node => {
        node.style.touchAction='none';
        node.addEventListener('pointerdown',event=>{
          if(event.button!==0)return;
          event.preventDefault();
          node.setPointerCapture(event.pointerId);
          this.held.begin(node.dataset.direction,event.pointerId);
        });
        node.addEventListener('pointerup',event=>{event.preventDefault();this.held.end(event.pointerId);});
        node.addEventListener('pointercancel',event=>this.held.end(event.pointerId,true));
        node.addEventListener('lostpointercapture',event=>this.held.end(event.pointerId,true));
        node.addEventListener('click',event=>{if(event.detail===0)this.held.click(node.dataset.direction);});
      });
      document.addEventListener('keydown', event => this.key(event));
      document.addEventListener('keyup', event => this.held.end(event.code));
      window.addEventListener('blur', () => this.suspend());
      document.addEventListener('visibilitychange', () => { if (document.hidden) this.suspend(); });
    }
    window.addEventListener('pagehide', () => { this.held.end(undefined,true); clearInterval(this.expiry); this.poller.stop(); });
  }
  revoke() {
    if (this.state?.state !== 'ARMED') return;
    this.revokedGenerations.add(this.state.generation);
    while (this.revokedGenerations.size > 16) this.revokedGenerations.delete(this.revokedGenerations.values().next().value);
  }
  update(state) {
    if (Number.isFinite(state?.observed_at) && Number.isFinite(this.lastConfirmed?.observed_at) && state.observed_at < this.lastConfirmed.observed_at) return;
    this.observationFailed = !state || state.state === 'UNKNOWN' || state.stale === true;
    if (state?.contract_version === 1 && ['ARMED','DISARMED','ESTOP'].includes(state.state) && state.generation) {
      this.lastConfirmed = state; this.lastArmed = state.state === 'ARMED';
    }
    this.state = state?.state === 'UNKNOWN' || !state ? this.lastConfirmed : state;
    if (this.generation !== this.state?.generation) { this.generation = this.state?.generation; this.seq = -1; }
    this.seq = Math.max(this.seq, Number.isInteger(state?.last_seq) ? state.last_seq : -1);
    for (const ack of [...(state?.recent_acks || []), state?.last_ack].filter(Boolean)) this.ack(ack);
    this.render();
  }
  controlsActive() { return this.interactive && (document.body.dataset.page !== 'system' || document.getElementById('admin-mode')?.checked === true); }
  now() { return Date.now() / 1000 + this.upperOffset; }
  commandTime() { return Date.now() / 1000 + this.lowerOffset; }
  async prepare(action) {
    const operator = this.state?.arming_mode === 'operator' && !['arm','clear_estop'].includes(action);
    await prepareMutation({ control: operator });
    if (!operator) await this.poller.refresh();
  }
  clockFresh() { const age = Date.now() / 1000 - this.clockObserved; return this.clockReady && age >= 0 && age <= 3; }
  can(owner = 'manual', action = 'move') {
    const settingsReady = !this.controls || (this.controls.commandReady?.() ?? this.controls.ready());
    return settingsReady && this.state?.execution_context !== 'test' && this.controlsActive()
      && !this.revokedGenerations.has(this.state?.generation)
      && (this.clockReady && operatorAuthorized(this.state, owner, action) || this.clockFresh() && authorized(this.state, owner, action, this.now()));
  }
  envelope(action, params = {}, owner = 'manual') {
    const permissionAction = ['arm','clear_estop'].includes(action);
    if (!this.clockReady || (!permissionAction && !operatorAuthorized(this.state, owner, action) && (!safetyKnown(this.state, this.now()) || !this.clockFresh()))) throw new Error(tr('Brak świeżego kontraktu bezpieczeństwa v1 i potwierdzonego zegara', 'No fresh safety contract v1 and confirmed clock'));
    if (!['arm', 'clear_estop'].includes(action) && (!this.can(owner, action) || (action === 'move' && params.yaw && !this.can(owner, 'turn')))) throw new Error(tr('Napęd zablokowany: stan, właściciel lub możliwości', 'Actuator blocked: state, owner or capability'));
    if (action === 'arm' && this.state.state !== 'DISARMED' || action === 'clear_estop' && this.state.state !== 'ESTOP') throw new Error(tr('Stan zmienił się — sprawdź ponownie zgodę', 'State changed — review permission again'));
    return this.buildEnvelope(action, params, this.state.generation);
  }
  buildEnvelope(action, params, generation) {
    return { ...params, action, source: 'manual', execution_context: 'panel', generation, seq: ++this.seq,
      request_id: requestId('web'),
      ts: this.commandTime(), ttl_ms: 500 };
  }
  commandParams(action,params) {
    if (action === 'move' && this.controls) params = this.controls.pulse(params.direction);
    if (['turn', 'height', 'balance', 'stabilization', 'action'].includes(action) && this.controls) params.settings_revision = this.controls.state?.revision;
    return params;
  }
  validatePulse(action,params) {
    if (['move', 'turn'].includes(action) && params.device_settings !== true && (![params.vx, params.yaw, params.duration].every(Number.isFinite)
      || Math.abs(params.vx) > 1 || Math.abs(params.yaw) > 1 || params.duration < .01 || params.duration > .25)) throw new Error(tr('Nieprawidłowy impuls: wartości -1–1, czas 0.01–0.25 s', 'Invalid pulse: values -1–1, duration 0.01–0.25 s'));
  }
  validateCommand(action,params) {
    if (action === 'arm' && params.arming_mode !== 'operator' && (!Number.isFinite(params.lease_s) || params.lease_s <= 0 || params.lease_s > 30))
      throw new Error('invalid_lease');
    this.validatePulse(action,params);
    if (action === 'height' && (!Number.isInteger(params.height) || params.height < 75 || params.height > 115)) throw new Error(tr('Wysokość musi być liczbą całkowitą 75–115', 'Height must be an integer 75–115'));
    if (action === 'action' && (!Number.isInteger(params.action_id) || params.action_id < 1 || params.action_id > 255)) throw new Error(tr('ID akcji musi być liczbą całkowitą 1–255', 'Action ID must be an integer 1–255'));
  }
  needsSettingsRefresh(action) {
    return action === 'move' && this.controls && this.state?.arming_mode !== 'operator';
  }
  confirmSendSettings(action,params) {
    if (action === 'move' && this.controls) {
      const revision = params.settings_revision;
      if (this.controls.state.revision !== revision) throw new Error(tr('Ustawienia zmieniły się — sprawdź wartości i kliknij ponownie.', 'Settings changed — review values and click again.'));
      return this.controls.pulse(params.direction);
    }
    return params;
  }
  commandForSend(action,params,owner,exempt) {
    let command;
    try {
      command = exempt ? { action, source: owner, request_id: requestId('web') } : this.envelope(action, params, owner);
    } catch (error) {
      if (!exempt) this.mutating = false;
      this.render();
      throw error;
    }
    return command;
  }
  recordCommand(command,exempt) {
    if (exempt) { this.held.stop(); this.toggleEpoch++; this.revoke(); this.render(); }
    const submittedAt = this.commandTime();
    const entry = { command, submittedAt, status: 'sending' };
    this.history.unshift(entry); this.history = this.history.slice(0, 20); this.pending.set(command.request_id, entry);
    for (const [id, pending] of this.pending) {
      if (!this.history.includes(pending)) this.pending.delete(id);
    }
    if (!exempt) this.mutating = true;
    this.renderHistory();
    return entry;
  }
  observeCommandResult(entry,result) {
    entry.status = result.status === 202 || result.data.pending ? 'pending' : 'awaiting_ack';
    if (result.data.safety) this.update(result.data.safety);
    if (result.data.ack) this.ack(result.data.ack, result.status === 200 && result.data.confirmed === true && result.data.pending !== true);
  }
  async send(action, params = {}, endpoint = '/api/control', owner = 'manual') {
    params=this.commandParams(action,params);
    const exempt = ['stop', 'disarm', 'estop'].includes(action);
    this.validateCommand(action,params);
    if (this.mutating && !exempt) throw new Error(tr('Poczekaj na odpowiedź poprzedniego żądania', 'Wait for the previous request'));
    if (!this.controlsActive() && !['arm', 'clear_estop', 'stop', 'disarm', 'estop'].includes(action)) throw new Error('Motion controls are unavailable on this view');
    if (!exempt) {
      this.mutating = true; this.render();
      try {
        await this.prepare(action);
        if (this.needsSettingsRefresh(action)) await this.controls.refresh();
        // Keep revision confirmation, envelope creation and dispatch in this continuation.
        params=this.confirmSendSettings(action,params);
      } catch (error) { this.mutating = false; this.render(); throw error; }
    }
    const command=this.commandForSend(action,params,owner,exempt);
    const entry=this.recordCommand(command,exempt);
    try {
      const result = await request(endpoint, { method: 'POST', body: command });
      this.observeCommandResult(entry,result);
      return result.data;
    } catch (error) {
      entry.status = error.status ? 'rejected' : 'unknown'; entry.reason = error.message;
      this.pending.delete(command.request_id); throw error;
    } finally { if (!exempt) { this.mutating = false; } this.renderHistory(); void this.poller.refresh(); }
  }
  async sendIntent(intent, valid) {
    const revision=this.controls?.state?.revision;
    const generation=this.state?.generation, initialSeq=this.seq;
    const permittedAtStart=this.can('manual',['left','right'].includes(intent.direction)?'turn':'move');
    const neutralAllowed=intent.mode==='release' && permittedAtStart;
    await prepareMutation({ control: true });
    const check=()=>{
      if(!valid() || (this.state && generation!==this.state.generation) || revision!==this.controls?.state?.revision
        || (!(neutralAllowed && !this.state && Date.now()/1000-this.clockObserved<=3) && !this.can('manual',['left','right'].includes(intent.direction)?'turn':'move')))
        throw new Error('manual_intent_cancelled_or_stale');
    };
    check();
    const params={...this.controls.pulse(intent.direction),mode:intent.mode};
    if(neutralAllowed && !this.state)this.seq=Math.max(this.seq,initialSeq);
    // New release intent: create its envelope only after negotiation and validation.
    const command=neutralAllowed && !this.state
      ?this.buildEnvelope('move',params,generation):this.envelope('move',params);
    const result=await request('/api/control',{method:'POST',body:command,timeout:500,beforeSend:check});
    if(result.data.safety)this.update(result.data.safety);
    if(result.data.ack?.status==='rejected')throw new Error(result.data.ack.reason||'motion_rejected');
    text('operator-message',intentLabel(intent.mode));
    return result.data;
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
    if (!this.clockReady || !['DISARMED','ESTOP'].includes(this.state?.state) || !this.state?.generation) return;
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
    const known = this.state?.contract_version === 1 && ['ARMED','DISARMED','ESTOP'].includes(this.state.state);
    const armed = known && this.state.state === 'ARMED';
    const unknownArmed = !known && this.lastArmed;
    const unconfirmed = this.observationFailed || !safetyKnown(this.state, this.now());
    node.textContent = armingLabel(known,armed,unconfirmed);
    node.classList.toggle('is-armed', armed); node.classList.toggle('is-disarmed', known && !armed);
    node.setAttribute('aria-pressed', String(armed));
    node.disabled = !armed && (this.toggling || this.mutating || !known || !this.clockReady);
    node.title = (armed || unknownArmed) ? tr('Kliknij, aby zatrzymać i rozbroić. Uzbrojenie trwa do decyzji operatora.',
      'Click to stop and disarm. Arming remains until the operator disarms.') : tr(
      'Kliknięcie zezwala na sterowanie z panelu. Przygotuj przestrzeń i kabel.',
      'Click to permit panel control. Prepare space and cable.');
  }
  stop() { this.send('stop').catch(showError); }
  suspend() {
    this.held.end(undefined,true);
    // Focus loss cancels the gesture, not the executor's operator permission.
    if (this.state?.arming_mode === 'operator' && this.state?.execution_context === 'panel') {
      this.render(); return;
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
    const speed = speedText?.trim() ? Number(speedText) : Number.NaN;
    const yaw = yawText?.trim() ? Number(yawText) : Number.NaN;
    const values = { forward: [speed, 0], backward: [-speed, 0], left: [0, -yaw], right: [0, yaw] }[direction];
    if (!values) return;
    this.send('move', { vx: values[0], yaw: values[1], duration: durationText?.trim() ? Number(durationText) : Number.NaN }).catch(showError);
  }
  key(event) {
    if (!this.controlsActive()) return;
    if (editingTarget(event.target) || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
    if (event.code === 'Space') { event.preventDefault(); this.stop(); return; }
    if (!['control','calibration'].includes(document.body.dataset.page) || !this.can()) return;
    const direction = { KeyW: 'forward', ArrowUp: 'forward', KeyS: 'backward', ArrowDown: 'backward', KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right' }[event.code];
    if (direction) { event.preventDefault(); this.held.begin(direction,event.code); }
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
    text('safety-state', this.state?.state || 'UNKNOWN');
    text('safety-ready', known && this.state.ready === true && this.state.hardware_ready === true ? tr('gotowy wykonawca', 'executor ready') : tr('niepotwierdzona / brak', 'unconfirmed / unavailable'));
    text('safety-age', `${ageOf(this.state, this.now())?.toFixed(1) ?? '—'} s`);
    text('safety-owner', known ? this.state.owner || '—' : '—');
    text('safety-reason', permissionReason(this,known));
    text('safety-lease', known && typeof this.state.lease_remaining_s === 'number' ? `${Math.max(0, this.state.lease_remaining_s - Math.max(0, this.now() - this.state.observed_at)).toFixed(1)} s` : '—');
    document.querySelectorAll('[data-direction]').forEach(node => { node.disabled = !this.can('manual', ['left', 'right'].includes(node.dataset.direction) ? 'turn' : 'move'); });
    this.onChange(this.state);
  }
  renderHistory() {
    const node = document.getElementById('request-history'); if (!node) return;
    node.replaceChildren(...this.history.map(entry => {
      const row = document.createElement('li');
      const reason=entry.reason?' · '+entry.reason:'';
      const completion=entry.ack?.status==='executed'?' · '+tr('fizyczne zakończenie niepotwierdzone','physical completion unverified'):'';
      row.textContent = `${new Date(entry.submittedAt * 1000).toLocaleTimeString()} · ${entry.command.action} · ${statusLabel(entry.status)}${reason}${completion}`;
      return row;
    }));
  }
}
