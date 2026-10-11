import { serviceActionBlock } from './service-actions.js';
import { catalogKnown, fresh, displayValue } from './model.js';
import { request, poll } from './transport.js';
import { el, kv, freshPill, button, details, tr, ageLabel, ageStamp, text, showError, rawDetails } from './ui.js';
export class System {
  constructor(safety) {
    this.safety = safety; this.catalog = null; this.services = null; this.resources = new Map();
    this.busy = new Set(); this.results = new Map();
    this.logBusy = new Set(); this.logResults = new Map(); this.version = null;
    this.expandedDetails = new Map();
    request('/api/status/version').then(result => { this.version = result.data; this.render(); }, () => {});
    document.getElementById('rescue-inspect')?.addEventListener('click', () => this.inspectRescue());
    document.getElementById('rescue-release')?.addEventListener('click', () => this.release());
    for (const id of ['rescue-confirm', 'rescue-consent']) document.getElementById(id)?.addEventListener('input', () => this.renderRescue());
    document.getElementById('rescue-resource')?.addEventListener('change', () => {
      document.getElementById('rescue-owners').replaceChildren(); document.getElementById('rescue-consent').checked = false;
      document.getElementById('rescue-confirm').value = ''; text('rescue-status', 'unknown'); this.resources.clear(); this.renderRescue();
    });
    this.poller = poll(async () => {
      const [catalog, services, graph, system] = await Promise.allSettled([request('/api/logic/catalog'), request('/svc'), request('/api/services/graph'), request('/sysinfo')]);
      this.catalog = catalog.status === 'fulfilled' ? catalog.value.data : null;
      this.services = services.status === 'fulfilled' ? services.value.data : null;
      this.graph = graph.status === 'fulfilled' ? graph.value.data : null;
      this.system = system.status === 'fulfilled' ? system.value.data : null;
      this.render();
      if (!this.catalog || !this.services) throw new Error(tr('Część danych systemu niedostępna', 'Some system data unavailable'));
    }, { interval: 5000, onError: showError });
  }
  rememberDetails(target) {
    for (const node of target?.querySelectorAll?.('details[data-system-detail]') || []) {
      this.expandedDetails.set(node.dataset.systemDetail, node.open === true);
    }
  }
  keepDetails(key, node, defaultOpen = false) {
    node.dataset.systemDetail = key;
    node.open = this.expandedDetails.has(key) ? this.expandedDetails.get(key) : defaultOpen;
    return node;
  }
  async action(row, action) {
    const blocked = serviceActionBlock(row, action, this);
    if (blocked) return showError(new Error(this.blockLabel(blocked)));
    const body = { action };
    if (row.can_move && ['start', 'restart'].includes(action)) {
      this.busy.add(row.unit);
      try {
        await this.safety.prepare();
        const envelope = this.safety.envelope('move', {}, row.motion_owner);
        for (const key of ['generation', 'seq', 'source', 'ts', 'ttl_ms', 'request_id']) body[key] = envelope[key];
      } catch (error) { this.busy.delete(row.unit); this.render(); throw error; }
    }
    this.busy.add(row.unit); this.results.set(row.unit, 'pending'); this.render();
    try {
      const result = await request(`/svc/${encodeURIComponent(row.unit)}`, { method: 'POST', body, timeout: 20000 });
      this.results.set(row.unit, result.status === 202 || result.data.pending ? 'pending' : result.data.ok ? tr('odpowiedź usługi odebrana', 'service response received') : 'rejected');
      text('operator-message', JSON.stringify(result.data));
    } catch (error) { this.results.set(row.unit, error.status ? `rejected: ${error.message}` : 'unknown'); showError(error); }
    finally { this.busy.delete(row.unit); this.render(); this.poller.refresh(); this.safety.poller.refresh(); }
  }
  render() {
    const target = document.getElementById('service-list'); if (!target) return;
    this.rememberDetails(target);
    this.rememberDetails(document.getElementById('system-details-data'));
    const valid = catalogKnown(this.catalog) && this.services?.contract_version === 2 && fresh(this.services, 10);
    text('system-contract', valid ? `v2 · ${ageLabel(this.services)}` : tr('Niepełne / stare dane — tylko odczyt', 'Incomplete / old data — read only'));
    const rows = Array.isArray(this.services?.services) ? this.services.services : [];
    const groups = new Map();
    for (const row of rows) { const group = row.lifecycle || 'unknown'; if (!groups.has(group)) groups.set(group, []); groups.get(group).push(row); }
    target.replaceChildren(...[...groups].map(([group, entries]) => {
      const section = el('section'); const groupName = { base: tr('Usługi bazowe', 'Base services'), startup: tr('Uruchamiane przy starcie', 'Startup services'), 'on-demand': tr('Uruchamiane na żądanie', 'On demand services'), on_demand: tr('Uruchamiane na żądanie', 'On demand services'), dev: tr('Narzędzia deweloperskie', 'Development tools') }[group] || group; section.append(el('h2', '', groupName));
      const grid = el('div', 'operator-grid');
      for (const row of entries) {
        const card = el('article', 'c-card');
        const identity = `${row.host || 'pi'}:${row.unit}`;
        const current = valid && fresh(row, 10) && (row.load_state ?? row.load) === 'loaded' && !row.error;
        card.append(el('h3', '', row.label || row.unit), freshPill(row, current ? row.active_state || row.active || 'unknown' : 'unknown', current && (row.active_state ?? row.active) === 'active' ? 'ok' : row.error || (row.active_state ?? row.active) === 'failed' ? 'err' : 'warn'),
          kv([[tr('Jednostka', 'Unit'), row.unit], [tr('Źródło', 'Source'), row.source || 'unknown'], [tr('Wiek odczytu', 'Observation age'), ageStamp(row, 10)],
            [tr('Konsumenci', 'Consumers'), (row.consumers || []).join(', ')], [tr('Zależności', 'Dependencies'), (row.dependencies || []).join(', ')],
            [tr('Powód / błąd', 'Reason / error'), row.error || row.reason || row.sub_state || row.sub], [tr('Autostart', 'Autostart'), (row.unit_file_state ?? row.enabled)]]));
        const actions = el('div', 'operator-row');
        for (const action of ['start', 'stop', 'restart']) {
          const reason = serviceActionBlock(row, action, this);
          const label = { start: tr('Uruchom', 'Start'), stop: tr('Zatrzymaj', 'Stop'), restart: tr('Uruchom ponownie', 'Restart') }[action];
          const control = button(label, () => this.action(row, action).catch(showError), Boolean(reason));
          if (reason) control.title = this.blockLabel(reason);
          actions.append(control);
        }
        card.append(actions);
        const reasons = [...new Set(['start', 'stop', 'restart'].map(action => serviceActionBlock(row, action, this)).filter(Boolean))];
        if (reasons.length) card.append(el('p', 'operator-muted', reasons.map(reason => this.blockLabel(reason)).join(' · ')));
        const autostart = el('div', 'operator-row');
        autostart.append(el('span', '', tr('Osobna zmiana autostartu:', 'Separate autostart change:')));
        for (const action of ['enable', 'disable']) {
          const reason = serviceActionBlock(row, action, this);
          const control = button(action === 'enable' ? tr('Włącz autostart', 'Enable autostart') : tr('Wyłącz autostart', 'Disable autostart'), () => this.action(row, action).catch(showError), Boolean(reason));
          if (reason) control.title = this.blockLabel(reason);
          autostart.append(control);
          if (reason) autostart.append(el('span', 'operator-muted', this.blockLabel(reason)));
        }
        card.append(this.keepDetails(`autostart:${identity}`, details(tr('Autostart', 'Autostart'), autostart)));
        if (this.results.has(row.unit)) card.append(el('p', 'operator-muted', this.results.get(row.unit)));
        card.append(button(tr('Odczytaj ostatnie logi', 'Read recent logs'), () => this.logs(row), !valid || this.logBusy.has(row.unit)));
        const logs = this.logResults.get(row.unit);
        if (logs) {
          const body = el('div'); body.append(kv([[tr('Źródło', 'Source'), logs.source], [tr('Wiek odczytu', 'Observation age'), ageStamp(logs, 60)]]), el('pre', 'operator-json', logs.error || (logs.lines || []).join('\n') || tr('Brak wpisów', 'No entries')));
          if (logs.truncated) body.append(el('p', '', tr('Odczyt ograniczony do 64 KiB / 50 linii', 'Read limited to 64 KiB / 50 lines')));
          card.append(this.keepDetails(`logs:${identity}`, details(tr('Logi na życzenie', 'Logs on demand'), body), true));
        }
        card.append(this.keepDetails(`source:${identity}`, rawDetails(row))); grid.append(card);
      }
      section.append(grid); return section;
    }));
    this.renderRescue();
    document.getElementById('system-details-data')?.replaceChildren(kv([
      ['CPU', displayValue(this.system?.cpu_pct, '%')], ['RAM', displayValue(this.system?.mem_pct ?? this.system?.mem?.pct, '%')],
      [tr('Dysk', 'Disk'), displayValue(this.system?.disk_pct, '%')], [tr('Temperatura', 'Temperature'), displayValue(this.system?.temp_c, ' °C')],
      [tr('Wiek pomiarów', 'Measurement age'), ageStamp(this.system, 10)], ['Git', this.version?.available ? `${this.version.branch || '—'} · ${this.version.commit || '—'}${this.version.dirty ? ' · dirty' : ''}` : 'unknown']
    ]), this.keepDetails('source:system', rawDetails({ system: this.system, graph: this.graph, version: this.version })));
    const wifi = this.graph?.network?.wifi;
    text('network-status', wifi ? `${wifi.status || 'unknown'} · ${(wifi.addresses || []).join(', ')} · ${wifi.interface || 'wlan0'}` : 'unknown');
  }
  blockLabel(reason) {
    const labels = {
      service_data_unavailable: ['Brak świeżych danych usług / katalogu', 'Fresh service / catalog data unavailable'],
      service_not_loaded_or_stale: ['Usługa niezainstalowana lub odczyt nieaktualny', 'Service not loaded or observation stale'],
      operation_pending: ['Operacja w toku', 'Operation pending'],
      permission_unknown: ['API nie potwierdziło uprawnień', 'API permissions unconfirmed'],
      motion_authorization_required: ['Brak zgody na ruch dla właściciela tej usługi', 'Motion authorization unavailable for this service owner'],
      movement_effect_unknown: ['Nieznany wpływ usługi na ruch', 'Movement effect unknown'],
      on_demand_autostart_forbidden: ['Usługa na żądanie — autostart niedozwolony', 'On demand service — autostart forbidden'],
      forbidden_on_api: ['Operacja chroniona dla serwera API', 'Operation protected for the API server'],
    };
    return labels[reason] ? tr(...labels[reason]) : reason;
  }
  async logs(row) {
    if (!catalogKnown(this.catalog) || this.logBusy.has(row.unit)) return;
    this.logBusy.add(row.unit); this.render();
    try { this.logResults.set(row.unit, (await request(`/api/services/${encodeURIComponent(row.unit)}/logs`, { timeout: 3000 })).data); }
    catch (error) { this.logResults.set(row.unit, { error: error.message, observed_at: null, source: 'unknown' }); showError(error); }
    finally { this.logBusy.delete(row.unit); this.render(); }
  }
  async inspectRescue() {
    const name = document.getElementById('rescue-resource').value;
    try {
      const data = (await request(`/api/resource/${encodeURIComponent(name)}`)).data;
      this.resources.set(name, data);
      const target = document.getElementById('rescue-owners'); target.replaceChildren();
      for (const owner of data.holders || []) {
        const label = el('label', 'operator-row'); const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.value = owner.pid;
        checkbox.addEventListener('change', () => this.renderRescue());
        checkbox.name = 'rescue-pid'; label.append(checkbox, el('span', '', `${owner.pid} · ${owner.service || owner.cmd || owner.command || '?'} · ${owner.user || '?'}`)); target.append(label);
      }
      target.append(rawDetails(data));
      text('rescue-status', `${data.state || 'unknown'} · ${ageLabel(data)}`);
    } catch (error) { this.resources.delete(name); text('rescue-status', 'unknown'); showError(error); }
    finally { this.renderRescue(); }
  }
  rescuePermitted() {
    const name = document.getElementById('rescue-resource')?.value, data = this.resources.get(name);
    const pids = [...document.querySelectorAll('[name="rescue-pid"]:checked')].map(node => Number(node.value));
    const permitted = new Set((data?.holders || []).map(owner => Number(owner.pid)));
    return catalogKnown(this.catalog) && data?.contract_version === 2 && fresh(data, 10)
      && data.state === 'busy' && data.free === false && !data.error && data.offline !== true
      && Array.isArray(data.consumers) && data.consumers.length === 0 && pids.length > 0
      && pids.every(pid => Number.isInteger(pid) && pid > 1 && permitted.has(pid))
      && document.getElementById('rescue-consent')?.checked === true && document.getElementById('rescue-confirm')?.value.trim() === name;
  }
  renderRescue() { const button = document.getElementById('rescue-release'); if (button) button.disabled = !this.rescuePermitted(); }
  async release() {
    const name = document.getElementById('rescue-resource').value;
    const pids = [...document.querySelectorAll('[name="rescue-pid"]:checked')].map(node => Number(node.value));
    if (!this.rescuePermitted()) {
      return showError(new Error(tr('Wymagany świeży odczyt, wybrane PID, nazwa zasobu i zgoda.', 'Fresh inventory, selected PIDs, resource name and consent are required.')));
    }
    const button = document.getElementById('rescue-release'); button.disabled = true;
    try {
      const result = await request(`/api/resource/${encodeURIComponent(name)}`, { method: 'POST', body: { action: 'release', pids, force: true, operator_consent: true }, timeout: 20000 });
      text('operator-message', JSON.stringify(result.data));
    } catch (error) { showError(error); }
    finally { document.getElementById('rescue-consent').checked = false; document.getElementById('rescue-confirm').value = ''; this.resources.delete(name); this.renderRescue(); }
  }
}
