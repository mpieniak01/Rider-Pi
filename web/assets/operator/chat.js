import { catalogKnown, taskCanStart, fresh } from './model.js';
import { request } from './transport.js';
import { el, tr, text, showError } from './ui.js';
export class Chat {
  constructor(tasks) {
    this.tasks = tasks; this.busy = false; this.providers = []; this.history = [];
    try {
      const stored = JSON.parse(sessionStorage.getItem('chat_history') || '[]');
      if (Array.isArray(stored)) for (const item of stored.slice(-80)) if (typeof item.text === 'string') this.message(['you', 'operator'].includes(item.role) ? 'operator' : 'assistant', item.text, false);
    } catch { /* Missing storage does not grant any task permission. */ }
    document.getElementById('chat-form')?.addEventListener('submit', event => { event.preventDefault(); this.send(); });
    this.loadProviders();
  }
  async loadProviders() {
    try {
      this.providers = (await request('/api/voice/providers')).data.providers || [];
      const select = document.getElementById('chat-provider');
      select.replaceChildren(...this.providers.map(provider => { const option = el('option', '', `${provider.label || provider.id} · ${provider.status?.state || 'unknown'}`); option.value = provider.id; return option; }));
    } catch (error) { text('chat-status', tr('Lista TTS niedostępna; chat tekstowy pozostaje dostępny po przygotowaniu domeny.', 'TTS catalog unavailable; text chat requires its prepared domain.')); }
  }
  message(role, value, save = true) {
    const row = el('article', `operator-chat-message is-${role}`);
    row.append(el('strong', '', role === 'operator' ? tr('Operator', 'Operator') : tr('Asystent', 'Assistant')), el('p', '', value));
    document.getElementById('chat-board').append(row);
    this.history.push({ role, text: value.slice(0, 20000) }); this.history = this.history.slice(-80);
    if (save) try { sessionStorage.setItem('chat_history', JSON.stringify(this.history)); } catch { /* Text remains in this view. */ }
  }
  async prepareDomain(kind, domain) {
    if (!catalogKnown(this.tasks.catalog)) throw new Error(tr('Brak aktualnego katalogu domen', 'No current domain catalog'));
    const task = this.tasks.catalog.features.find(row => row.option_kind === kind);
    if (!task || task.can_move !== false || !task.option_schema?.choices?.some(choice => choice.value === domain)) throw new Error(tr('Domena niedostępna', 'Domain unavailable'));
    if (task.requested && task.options?.domain !== domain) throw new Error(tr('Zakończ poprzednią domenę przed zmianą profilu.', 'End the previous domain before changing its profile.'));
    if (task.ready === true && task.can_move === false && fresh(task, 10) && task.options?.domain === domain) return;
    if (!taskCanStart(task, this.tasks.catalog, this.tasks.safety.state)) throw new Error(tr('Domena nie jest gotowa', 'Domain not ready'));
    this.tasks.options.set(task.name, { domain });
    const result = await request(`/api/logic/feature/${encodeURIComponent(task.name)}`, { method: 'POST', body: { enabled: true, options: { domain } }, timeout: 20000 });
    this.tasks.poller.refresh();
    const observed = result.data.result?.task;
    if (result.status === 202 || result.data.ok !== true || observed?.name !== task.name || observed.ready !== true || observed.can_move !== false || observed.options?.domain !== domain || !fresh(observed, 10)) throw new Error(observed?.error || tr('Przygotowanie domeny oczekuje; ponów wysłanie po potwierdzeniu.', 'Domain preparation pending; send again after confirmation.'));
  }
  async send() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim(); if (!message || this.busy) return;
    this.busy = true; document.getElementById('chat-send').disabled = true;
    text('chat-status', tr('Przygotowuję wyłącznie potrzebną domenę i wysyłam…', 'Preparing only the required domain and sending…'));
    try {
      // Only an explicit send may prepare a domain. Viewing/selecting is GET-only.
      await this.prepareDomain('provider', 'text');
      const tts = document.getElementById('chat-tts').checked;
      const provider = this.providers.find(row => row.id === document.getElementById('chat-provider').value);
      if (tts && !provider) throw new Error(tr('Wybierz dostępny provider TTS', 'Select an available TTS provider'));
      if (tts && provider?.service) await this.prepareDomain('voice', 'tts');
      this.message('operator', message); input.value = '';
      const result = await request('/api/chat/send', { method: 'POST', body: { msg: message, user: 'web' }, timeout: 30000 });
      const data = result.data;
      if (data.ok === false || data.source === 'echo') throw new Error(tr('Domena nie odpowiedziała; echo nie potwierdza działania AI.', 'The domain did not answer; echo does not confirm AI operation.'));
      const reply = data.reply ?? data.text ?? data.message ?? data.content ?? data.item?.msg;
      if (typeof reply !== 'string') throw new Error(tr('Odpowiedź bez treści', 'Response contains no text'));
      this.message('assistant', reply); text('chat-status', tr('Odpowiedź odebrana', 'Response received'));
      if (tts) await this.speak(reply, provider);
    } catch (error) { showError(error); text('chat-status', error.message); }
    finally { this.busy = false; document.getElementById('chat-send').disabled = !catalogKnown(this.tasks.catalog); }
  }
  async speak(reply, provider) {
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch('/api/voice/tts', { method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: reply, provider: provider.id, backend: provider.backend || provider.id, voice: provider.voice, model: provider.model }) });
      if (!response.ok) throw new Error(`TTS HTTP ${response.status}`);
      if (response.headers.get('X-Voice-Fallback')) throw new Error(tr('Zastępczy dźwięk nie potwierdza działania TTS.', 'Fallback audio does not confirm TTS operation.'));
      const url = URL.createObjectURL(await response.blob()); const audio = el('audio'); audio.controls = true; audio.src = url;
      audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true });
      document.getElementById('chat-board').append(audio);
      setTimeout(() => URL.revokeObjectURL(url), 120000);
    } finally { clearTimeout(timeout); }
  }
}
