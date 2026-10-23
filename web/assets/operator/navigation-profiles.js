import { request, poll } from './transport.js';
import { text, showError } from './ui.js';
import { profileText as t } from './navigation-profile-messages.js';

const ids = ['legacy', 'cautious', 'balanced', 'fluid'];
const legacy = { version: 1, profile_id: 'legacy', profile_revision: 1 };
function selection(value) {
  return value?.version === 1 && ids.includes(value.profile_id)
    && Number.isSafeInteger(value.profile_revision) && value.profile_revision > 0
    ? { version: 1, profile_id: value.profile_id, profile_revision: value.profile_revision } : null;
}
export function profileCatalog(policy) {
  const raw = policy?.behavior_catalog, active = selection(raw?.active) || selection(policy?.behavior) || legacy;
  const fallback = { supported: false, active, profiles: [{ id: active.profile_id,
    profile_revision: active.profile_revision, status: active.profile_id === 'legacy' ? 'legacy' : 'experimental', parameters: {} }] };
  if (raw?.version !== 1 || raw.supported !== true || !Array.isArray(raw.profiles)
    || !/^[a-f0-9]{64}$/.test(raw.effective_policy_sha256 || '') || !selection(raw.active)) return fallback;
  const profiles = [];
  for (const row of raw.profiles) {
    if (!ids.includes(row.id) || !Number.isSafeInteger(row.profile_revision) || row.profile_revision < 1
      || row.status !== (row.id === 'legacy' ? 'legacy' : 'experimental')
      || profiles.some(item => item.id === row.id)) return fallback;
    profiles.push(row);
  }
  if (!profiles.some(row => row.id === active.profile_id && row.profile_revision === active.profile_revision)) return fallback;
  return { ...raw, profiles, active };
}
function errorKey(error) {
  const code = String(error.data?.error?.code || error.data?.error || error.message || '');
  if (/stop_goals|stop_loops/.test(code)) return 'behavior.block.observation';
  if (/conflict|changed/.test(code)) return 'behavior.conflict';
  if (/active|idle|motion|stopped/.test(code)) return 'behavior.block.motion';
  return 'behavior.failed';
}
export class NavigationProfiles {
  constructor(safety) {
    this.safety = safety; this.policy = null; this.status = null; this.pipeline = null;
    this.draft = null; this.editBase = null; this.busy = false; this.epoch = 0; this.error = ''; this.saved = null;
    const select = document.getElementById('navigation-profile');
    select?.addEventListener('focus', () => { this.editBase = this.base(); });
    select?.addEventListener('blur', () => { this.editBase = null; });
    select?.addEventListener('change', () => {
      const row = profileCatalog(this.policy).profiles.find(item => item.id === select.value);
      if (!row) return;
      this.draft = { ...(this.draft || this.editBase || this.base()),
        selection: { version: 1, profile_id: row.id, profile_revision: row.profile_revision } };
      this.error = ''; this.saved = null; this.render();
    });
    document.getElementById('navigation-profile-apply')?.addEventListener('click', () => void this.apply());
    document.getElementById('navigation-profile-refresh')?.addEventListener('click', () => void this.refresh());
    this.poller = poll(() => this.load(), { interval: 3000, onError: () => {
      this.policy = null; this.status = null; this.pipeline = null; this.error = 'behavior.block.stale'; this.render();
    } });
    window.addEventListener('dashboard:langchange', () => this.render());
    this.render();
  }
  base() { return { revision: this.policy?.revision, hash: profileCatalog(this.policy).effective_policy_sha256 }; }
  stale(draft = this.draft) {
    if (!draft) return false;
    const catalog = profileCatalog(this.policy), base = this.base();
    return !catalog.supported || draft.revision !== base.revision || draft.hash !== base.hash
      || !catalog.profiles.some(row => row.id === draft.selection?.profile_id && row.profile_revision === draft.selection?.profile_revision);
  }
  async load() {
    if (this.busy) return;
    const epoch = this.epoch;
    const [policy, status, pipeline] = await Promise.all([
      request('/api/navigation/config'), request('/api/navigation/status'), request('/api/resource/camera/pipeline'),
    ]);
    if (epoch !== this.epoch || this.busy) return;
    this.policy = policy.data; this.status = status.data; this.pipeline = pipeline.data;
    this.render();
  }
  blocked() {
    if (!profileCatalog(this.policy).supported) return 'behavior.unsupported';
    if (this.stale()) return 'behavior.conflict';
    if (this.pipeline?.profile?.analysis_location === 'local'
      && (this.draft?.selection.profile_id || profileCatalog(this.policy).active.profile_id) !== 'legacy') return 'behavior.localOnly';
    const safety = this.safety?.state;
    if (!safety || safety.stale === true || !['ARMED', 'DISARMED', 'ESTOP'].includes(safety.state)
      || this.safety.clockFresh?.() !== true) return 'behavior.block.stale';
    if (safety.moving === true || ['active', 'qualifying'].includes(safety.operator_control?.state)
      || this.status?.mode === 'drive' && this.status?.running === true) return 'behavior.block.motion';
    if (this.status?.running === true) return 'behavior.block.observation';
    return this.busy ? 'behavior.block.busy' : '';
  }
  render() {
    for (const [id, key] of [
      ['navigation-profile-title', 'behavior.title'], ['navigation-profile-hint', 'behavior.hint'],
      ['navigation-profile-label', 'behavior.select'], ['navigation-profile-parameters-label', 'behavior.parameters'],
      ['navigation-temporal-title', 'temporal.title'],
    ]) text(id, t(key));
    const catalog = profileCatalog(this.policy), selected = this.draft?.selection.profile_id || catalog.active.profile_id;
    const row = catalog.profiles.find(item => item.id === selected), select = document.getElementById('navigation-profile');
    if (select) {
      const choices = JSON.stringify([(catalog.supported ? catalog.profiles : ids.map(id => ({ id }))).map(item => [item.id, item.status]), selected, document.documentElement.lang]);
      if (select.dataset.choices !== choices && document.activeElement !== select) {
        select.dataset.choices = choices;
        select.replaceChildren(...(catalog.supported ? catalog.profiles : ids.map(id => ({ id }))).map(item => {
          const option = document.createElement('option'); option.value = item.id;
          option.textContent = t('behavior.profile.' + item.id) + (item.status === 'experimental' ? ' · ' + t('behavior.experimental') : '');
          option.selected = selected === item.id; option.disabled = !catalog.supported; return option;
        }));
      }
      select.disabled = !catalog.supported || this.busy;
    }
    text('navigation-profile-current', t('behavior.current', { profile: t('behavior.profile.' + catalog.active.profile_id), revision: this.policy?.revision ?? '—' }));
    text('navigation-profile-draft', this.draft ? t('behavior.draft', { profile: t('behavior.profile.' + selected) }) : '');
    text('navigation-profile-description', t('behavior.description.' + selected));
    text('navigation-profile-provider-hint', this.pipeline?.profile?.analysis_location === 'local'
      ? t('behavior.localOnly', { model: this.pipeline.profile.local_engine || '—' }) : '');
    text('navigation-profile-experimental', row?.status === 'experimental' ? t('behavior.experimentalHint') : '');
    text('navigation-profile-parameters', catalog.supported ? JSON.stringify(row?.parameters || {}, null, 2) : '');
    text('navigation-profile-hash', catalog.supported ? t('behavior.effectiveHash') + ': ' + catalog.effective_policy_sha256 : '');
    const block = this.blocked();
    text('navigation-profile-message', this.error || block ? t(this.error || block, { model: this.pipeline?.profile?.local_engine || '—' }) : this.saved === this.policy?.revision ? t('behavior.saved', { revision: this.saved }) : '');
    const apply = document.getElementById('navigation-profile-apply'), refresh = document.getElementById('navigation-profile-refresh');
    const changed = this.draft && (selected !== catalog.active.profile_id || this.draft.selection.profile_revision !== catalog.active.profile_revision);
    if (apply) { apply.textContent = t(this.busy ? 'behavior.saving' : 'behavior.apply'); apply.title = t('behavior.applyHint'); apply.disabled = !changed || !!block; }
    if (refresh) { refresh.textContent = t(this.draft ? 'behavior.discard' : 'behavior.refresh'); refresh.disabled = this.busy; }
    this.renderTemporal();
  }
  renderTemporal() {
    const decision = this.status?.decision, temporal = decision?.temporal;
    if (!temporal || typeof temporal.action !== 'string' || typeof temporal.state !== 'string') {
      text('navigation-temporal-state', t('temporal.none')); return;
    }
    const profile = decision.behavior, current = this.status.running === true && this.status.stale !== true;
    const reasonKey = "vision.reason." + (temporal.reason || "");
    const reason = t(reasonKey);
    const rows = [
      current ? '' : t('temporal.historical'),
      t('temporal.raw') + ': ' + (decision.raw_state || '—'),
      t('temporal.stabilized') + ': ' + (temporal.state || '—'),
      t('temporal.risk') + ': ' + (temporal.risk || '—') + ' / ' + temporal.action,
      t('behavior.title') + ': ' + (profile ? t('behavior.profile.' + profile.profile_id) + ' · r' + profile.profile_revision : '—'),
      t('temporal.reason') + ': ' + (temporal.reason ? (reason === reasonKey ? temporal.reason : reason) : t('temporal.noReason')),
      t('temporal.evidence') + ': ' + (temporal.evidence_frames ?? '—'),
      t('temporal.near') + ': ' + t(typeof temporal.near_guard_clear !== 'boolean' ? 'temporal.unknown' : temporal.near_guard_clear ? 'temporal.yes' : 'temporal.no'),
      Array.isArray(temporal.spatial?.boundary) && temporal.spatial.boundary.length ? t('temporal.boundary') + ': ' + temporal.spatial.boundary.length : t('temporal.noBoundary'),
    ];
    text('navigation-temporal-state', rows.filter(Boolean).join('\n'));
  }
  async refresh() {
    if (this.busy) return;
    this.draft = null; this.editBase = null; this.error = ''; this.saved = null; this.render();
    await this.poller.refresh(); this.render();
  }
  async apply() {
    const block = this.blocked();
    if (!this.draft || block) { if (block) { this.error = block; this.render(); } return; }
    const draft = this.draft, active = profileCatalog(this.policy).active;
    if (draft.selection.profile_id === active.profile_id && draft.selection.profile_revision === active.profile_revision) return;
    this.busy = true; this.epoch++; this.error = ''; this.saved = null; this.render();
    try {
      const response = await request('/api/navigation/config', { method: 'POST', body: {
        revision: draft.revision, values: { behavior: draft.selection },
      } });
      this.policy = response.data?.config || response.data; this.draft = null; this.editBase = null; this.saved = this.policy?.revision;
    } catch (error) {
      this.error = errorKey(error); showError(new Error(t(this.error)));
    } finally { this.epoch++; this.busy = false; this.render();
      try { await this.load(); } catch { this.error ||= 'behavior.block.stale'; this.render(); }
    }
  }
}
