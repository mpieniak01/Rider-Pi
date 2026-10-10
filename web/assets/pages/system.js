import { initI18n, t } from '/web/assets/i18n.js';

initI18n(localStorage.getItem('lang') || 'pl');
const graphEl = document.getElementById('system-graph');
const tableEl = document.getElementById('system-table');
const summaryEl = document.getElementById('system-summary');
const networkEl = document.getElementById('system-network');
const statusEl = document.getElementById('status-line');
const statuses = ['active', 'inactive', 'failed', 'unknown'];
const groupsOrder = ['core', 'motion', 'vision', 'voice', 'dev', 'cloud'];
const pillClasses = { active: 'is-ok', inactive: 'is-off', failed: 'is-err', unknown: 'is-warn' };
let inFlight = false;
let lastPayload = null;
let lastSuccess = null;
let lastError = false;
let renderedKey = null;

function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

function statusOf(node) {
  return statuses.includes(node.status) ? node.status : 'unknown';
}

function pill(node) {
  const status = statusOf(node);
  return element('span', `status-pill ${pillClasses[status]}`, t(`system_ui.${status}`));
}

function groupLabel(group) {
  return groupsOrder.includes(group) ? t(`system_ui.group_${group}`) : group;
}

function renderStatus() {
  const time = lastSuccess ? lastSuccess.toLocaleTimeString(document.documentElement.lang) : null;
  statusEl.classList.toggle('is-stale', lastError);
  statusEl.textContent = lastError
    ? t(lastSuccess ? 'system_ui.stale' : 'system_ui.error', { time })
    : time ? t('system_ui.updated', { time }) : t('system_ui.loading');
}

function renderSummary(nodes) {
  summaryEl.replaceChildren(...statuses.map(status => {
    const count = nodes.filter(node => statusOf(node) === status).length;
    return element('span', `status-pill ${pillClasses[status]}`, `${t(`system_ui.${status}`)}: ${count}`);
  }));
}

function renderCard(node, labels) {
  const card = element('article', `c-card service-node is-${statusOf(node)}`);
  const header = element('div', 'service-node__head');
  header.append(element('h3', 'service-node__title', node.label || node.unit), pill(node));
  card.append(header, element('p', 'desc service-node__unit', `${t('system_ui.unit')}: ${node.unit || '—'}`));
  if (node.description) card.append(element('p', 'desc', node.description));
  if (node.since) card.append(element('p', 'desc service-node__since', `${t('system_ui.since')}: ${node.since}`));
  const edges = Array.isArray(node.edges_out) ? node.edges_out : [];
  if (edges.length) {
    card.append(element('p', 'desc', t('system_ui.connections')));
    const list = element('div', 'edge-list');
    edges.forEach(id => list.append(element('span', '', labels.get(id) || id)));
    card.append(list);
  }
  return card;
}

function renderGraph(nodes) {
  if (!nodes.length) {
    graphEl.replaceChildren(element('p', 'c-card no-services', t('system_ui.empty')));
    return;
  }
  const buckets = new Map();
  const labels = new Map(nodes.map(node => [node.id, node.label || node.unit]));
  nodes.forEach(node => {
    const group = node.group || 'other';
    if (!buckets.has(group)) buckets.set(group, []);
    buckets.get(group).push(node);
  });
  const entries = [...buckets.entries()].sort(([a], [b]) => {
    const rank = group => groupsOrder.includes(group) ? groupsOrder.indexOf(group) : groupsOrder.length;
    return rank(a) - rank(b) || a.localeCompare(b);
  });
  const sections = entries.map(([group, items]) => {
    const section = element('section', 'system-section');
    section.append(element('h2', 'section-title', groupLabel(group)));
    const grid = element('div', 'l-grid services-grid');
    items.sort((a, b) => (a.label || a.unit || '').localeCompare(b.label || b.unit || ''));
    items.forEach(node => grid.append(renderCard(node, labels)));
    section.append(grid);
    return section;
  });
  graphEl.replaceChildren(...sections);
}

function renderNetwork(wifi = {}) {
  if (!wifi || typeof wifi !== 'object') wifi = {};
  const status = ['connected', 'disconnected', 'blocked', 'no_address', 'missing'].includes(wifi.status)
    ? wifi.status : 'unknown';
  const tone = status === 'connected' ? 'is-ok' : status === 'blocked' ? 'is-err' : 'is-warn';
  const heading = element('h2', 'section-title', t('system_ui.network'));
  const card = element('article', 'c-card wifi-card');
  const header = element('div', 'service-node__head');
  header.append(element('h3', '', `Wi-Fi (${wifi.interface || 'wlan0'})`),
    element('span', `status-pill ${tone}`, t(`system_ui.wifi_${status}`)));
  card.append(header);
  const addresses = Array.isArray(wifi.addresses) ? wifi.addresses.join(', ') : '';
  const boot = wifi.autostart === true ? 'enabled' : wifi.autostart === false ? 'disabled' : 'unknown';
  const route = wifi.default_route === true ? 'yes' : wifi.default_route === false ? 'no' : 'unknown';
  card.append(element('p', 'desc', `${t('system_ui.wifi_addresses')}: ${addresses || '—'}`),
    element('p', 'desc', `${t('system_ui.wifi_route')}: ${t(`system_ui.${route}`)}${wifi.gateway ? ` (${wifi.gateway})` : ''}`),
    element('p', 'desc', `${t('system_ui.wifi_autostart')}: ${wifi.manager || 'dhcpcd'} / ${t(`system_ui.${boot}`)}`),
    element('p', 'desc', t('system_ui.wifi_scope')));
  networkEl.replaceChildren(heading, card);
}

function renderTable(nodes) {
  const header = element('tr');
  ['unit', 'description_header', 'status', 'group', 'since'].forEach(key => {
    const cell = element('th', '', t(`system_ui.${key}`));
    cell.scope = 'col';
    header.append(cell);
  });
  tableEl.tHead.replaceChildren(header);
  const rows = nodes.slice().sort((a, b) => (a.label || '').localeCompare(b.label || '')).map(node => {
    const row = element('tr');
    const description = element('td');
    description.append(element('div', '', node.label || '—'), element('div', 'desc', node.description || ''));
    const state = element('td');
    state.append(pill(node));
    row.append(element('td', '', node.unit || '—'), description, state,
      element('td', '', groupLabel(node.group || 'other')), element('td', '', node.since || '—'));
    return row;
  });
  tableEl.tBodies[0].replaceChildren(...rows);
}

function render(force = false) {
  document.title = `Rider-Pi — ${t('system_ui.title')}`;
  renderStatus();
  if (!lastPayload) return;
  const nodes = lastPayload.nodes;
  const key = JSON.stringify([nodes, lastPayload.network]);
  if (!force && key === renderedKey) return;
  renderedKey = key;
  renderSummary(nodes);
  renderNetwork(lastPayload.network?.wifi);
  renderGraph(nodes);
  renderTable(nodes);
}

async function loadGraph() {
  if (inFlight) return;
  inFlight = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch('/api/services/graph', { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (!Array.isArray(payload.nodes) || payload.nodes.some(node => !node || typeof node !== 'object')) {
      throw new Error('Invalid service graph');
    }
    lastPayload = payload;
    lastSuccess = new Date();
    lastError = false;
  } catch (error) {
    lastError = true;
    console.warn('Service diagnostics unavailable:', error);
  } finally {
    clearTimeout(timeout);
    inFlight = false;
    render();
  }
}

window.addEventListener('dashboard:langchange', () => render(true));
render();
loadGraph();
setInterval(loadGraph, 5000);
