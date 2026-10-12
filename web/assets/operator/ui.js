import { ageOf, displayValue } from './model.js';
const language = () => document.documentElement.lang.startsWith('en') ? 'en' : 'pl';
export function tr(pl, en = pl) { return language() === 'en' ? en : pl; }
export function el(tag, className = '', text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = displayValue(text);
  return node;
}
export function text(id, value) { const node = document.getElementById(id); if (node) node.textContent = displayValue(value); }
export function button(label, action, disabled = false, className = 'c-btn c-btn-sm') {
  const node = el('button', className, label); node.type = 'button'; node.disabled = disabled;
  node.addEventListener('click', action); return node;
}
export function pill(label, tone = 'warn') { return el('span', `c-pill is-${tone}`, label); }
export function powerLabel(value) {
  return value === true ? 'ON' : value === false ? 'OFF' : tr('Nieznany', 'Unknown');
}
export function statusLabel(value) {
  const labels = { ready: ['Gotowe', 'Ready'], starting: ['Uruchamianie', 'Starting'], stopping: ['Kończenie', 'Stopping'],
    stopped: ['Zakończone', 'Stopped'], failed: ['Błąd', 'Failed'], partial: ['Niepełne', 'Partial'],
    active: ['Aktywne', 'Active'], inactive: ['Nieaktywne', 'Inactive'], unknown: ['Nieznane', 'Unknown'],
    free: ['Wolny', 'Free'], busy: ['Zajęty', 'Busy'], pending: ['Oczekuje', 'Pending'],
    rejected: ['Odmowa', 'Rejected'], sending: ['Wysyłanie', 'Sending'], observed: ['Odpowiedź odebrana', 'Response received'],
    awaiting_ack: ['Oczekuje na ACK', 'Awaiting ACK'], executed: ['SDK przyjął', 'SDK accepted'] };
  return labels[value] ? tr(...labels[value]) : value || tr('Nieznane', 'Unknown');
}
export function freshPill(row, label, tone, maxAge = 10) {
  const node = pill(statusLabel(label), tone);
  const ts = row && Object.hasOwn(row, 'observed_at') ? row.observed_at : row?.ts;
  if (typeof ts === 'number' && Number.isFinite(ts)) node.dataset.statusTs = String(ts);
  node.dataset.statusMaxAge = String(maxAge);
  if (row?.stale || ageOf(row) === null || ageOf(row) > maxAge) { node.textContent = 'unknown / stale'; node.className = 'c-pill is-warn'; }
  return node;
}
export function details(title, body) {
  const node = el('details'); node.append(el('summary', '', title), body); return node;
}
export function kv(values) {
  const node = el('dl', 'operator-kv');
  for (const [name, value] of values) {
    const cell = el('dd');
    value?.nodeType === 1 ? cell.append(value) : cell.textContent = displayValue(value);
    node.append(el('dt', '', name), cell);
  }
  return node;
}
export function ageLabel(row) {
  const age = ageOf(row);
  return age === null ? tr('wiek nieznany', 'age unknown') : `${age.toFixed(1)} s`;
}
export function ageStamp(row, maxAge = 3) {
  const node = el('time', 'operator-age', ageLabel(row));
  const ts = row && Object.hasOwn(row, 'observed_at') ? row.observed_at : row?.ts;
  if (typeof ts === 'number' && Number.isFinite(ts)) node.dataset.observedAt = String(ts);
  node.dataset.maxAge = String(maxAge);
  return node;
}
export function refreshAges() {
  document.querySelectorAll('.operator-age').forEach(node => {
    const age = ageOf({ observed_at: Number(node.dataset.observedAt) });
    node.textContent = age === null ? tr('wiek nieznany', 'age unknown') : `${age.toFixed(1)} s${age > Number(node.dataset.maxAge) ? ' · stale' : ''}`;
    node.classList.toggle('operator-error', age === null || age > Number(node.dataset.maxAge));
  });
  document.querySelectorAll('[data-status-max-age]').forEach(node => {
    const age = ageOf({ observed_at: Number(node.dataset.statusTs) });
    if (age === null || age > Number(node.dataset.statusMaxAge)) { node.textContent = 'unknown / stale'; node.className = 'c-pill is-warn'; }
  });
}
export function showError(error) { text('operator-message', `${tr('Odmowa / błąd', 'Refused / error')}: ${error.message || error}`); }
export function localizeStatic() {
  document.querySelectorAll('[data-pl][data-en]').forEach(node => { node.textContent = language() === 'en' ? node.dataset.en : node.dataset.pl; });
}
export function rawDetails(data) { return details(tr('Dane źródłowe', 'Source data'), el('pre', 'operator-json', JSON.stringify(data, null, 2))); }
