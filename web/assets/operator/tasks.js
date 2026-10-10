import { catalogKnown, taskCanStart, nowSeconds } from './model.js';
import { request, poll } from './transport.js';
import { el, pill, freshPill, statusLabel, button, kv, tr, ageLabel, ageStamp, text, showError, rawDetails } from './ui.js';
export class Tasks {
  constructor(safety, target = 'task-list', filter = () => true) {
    this.safety = safety; this.target = document.getElementById(target); this.filter = filter;
    this.catalog = null; this.busy = new Set(); this.options = new Map(); this.results = new Map();
    this.poller = poll(async () => { this.catalog = (await request('/api/logic/catalog')).data; this.render(); },
      { interval: 5000, onError: error => { this.catalog = null; this.render(); showError(error); } });
  }
  choice(task) {
    const schema = task.option_schema;
    if (!schema || !Array.isArray(schema.choices) || !schema.field) return null;
    const label = el('label', 'operator-option', schema.field);
    const select = el('select'); select.id = `task-option-${task.name}`;
    for (const choice of schema.choices) {
      const option = el('option', '', tr(choice.label || choice.value, choice.label_en || choice.value)); option.value = choice.value; select.append(option);
    }
    select.value = this.options.get(task.name)?.[schema.field] ?? task.options?.[schema.field] ?? schema.default;
    select.disabled = task.requested === true || this.busy.has(task.name);
    select.addEventListener('change', () => this.options.set(task.name, { [schema.field]: select.value }));
    label.append(select); return label;
  }
  async change(task, enabled) {
    if (this.busy.has(task.name)) return;
    if (!catalogKnown(this.catalog) || (enabled && !taskCanStart(task, this.catalog, this.safety.state))) return;
    const options = this.options.get(task.name) || task.options || (task.option_schema ? { [task.option_schema.field]: task.option_schema.default } : {});
    if (enabled && task.option_schema?.end_value === options[task.option_schema.field]) enabled = false;
    const body = { enabled, options };
    if (enabled && task.can_move) {
      // Metadata is generated exactly once at the operator's click.
      const envelope = this.safety.envelope('move', {}, task.motion_owner);
      for (const key of ['generation', 'seq', 'source', 'ts', 'ttl_ms', 'request_id']) body[key] = envelope[key];
    }
    this.busy.add(task.name); this.results.set(task.name, { status: 'pending', submitted_at: nowSeconds() }); this.render();
    try {
      const { data, status } = await request(`/api/logic/feature/${encodeURIComponent(task.name)}`, { method: 'POST', body, timeout: 20000 });
      // Service activation is not an actuator completion acknowledgement.
      this.results.set(task.name, { status: status === 202 || data.pending ? 'pending' : data.ok === true ? 'observed' : 'rejected', data });
      text('operator-message', tr('Odpowiedź zadania odebrana. Fizyczne zakończenie ruchu wymaga obserwacji operatora.', 'Task response received. Physical motion completion requires operator observation.'));
    } catch (error) { this.results.set(task.name, { status: error.status ? 'rejected' : 'unknown', data: error.data, error: error.message }); showError(error); }
    finally { this.busy.delete(task.name); this.render(); this.poller.refresh(); this.safety.poller.refresh(); }
  }
  render() {
    if (!this.target) return;
    const valid = catalogKnown(this.catalog);
    text('catalog-status', valid ? `v2 · ${ageLabel(this.catalog)}` : tr('Katalog niedostępny lub stary — tylko odczyt', 'Catalog unavailable or old — read only'));
    if (!this.catalog?.features) { this.target.replaceChildren(el('p', 'operator-muted', tr('Brak potwierdzonej listy zadań.', 'No confirmed task list.'))); return; }
    const focus = document.activeElement?.id;
    this.target.replaceChildren(...this.catalog.features.filter(this.filter).map(task => {
      const card = el('article', 'c-card operator-task');
      const header = el('div', 'operator-row');
      header.append(el('h3', '', tr(task.title || task.name, task.title_en || task.name)), freshPill(task, valid ? task.state || 'unknown' : 'unknown', valid && task.ready === true && !task.stale ? 'ok' : task.error ? 'err' : 'warn'));
      card.append(header, el('p', '', tr(task.description || '', task.description_en || '')),
        kv([[tr('Ruch', 'Motion'), task.can_move === true ? tr('TAK — osobna zgoda', 'YES — separate consent') : task.can_move === false ? tr('bez napędów', 'no actuators') : tr('nieznany — start zablokowany', 'unknown — start blocked')],
          [tr('Właściciel sterowania', 'Control owner'), task.motion_owner], [tr('Źródło', 'Source'), task.source || 'unknown'], [tr('Wiek odczytu', 'Observation age'), ageStamp(task, 10)],
          [tr('Zasoby', 'Resources'), (task.resources || []).join(', ')]]));
      if (task.error) card.append(el('p', 'operator-error', task.error));
      const choice = this.choice(task); if (choice) card.append(choice);
      const actions = el('div', 'operator-row');
      actions.append(button(tr('Uruchom zadanie', 'Start task'), () => this.change(task, true).catch(showError), !valid || task.requested === true || !taskCanStart(task, this.catalog, this.safety.state) || (task.can_move && !this.safety.can(task.motion_owner)) || this.busy.has(task.name)),
        button(tr('Zakończ zadanie', 'End task'), () => this.change(task, false).catch(showError), !valid || !task.requested || this.busy.has(task.name)));
      card.append(actions);
      const result = this.results.get(task.name);
      if (result) card.append(pill(`${tr('Żądanie', 'Request')}: ${statusLabel(result.status)}`), rawDetails(result));
      card.append(rawDetails({ services: task.services, options: task.options, requested: task.requested, ready: task.ready, producer_statuses: task.producer_statuses, error: task.error }));
      return card;
    }));
    if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
  }
}
