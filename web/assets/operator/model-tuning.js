import { request, poll } from './transport.js';
import { text, showError } from './ui.js';
import { profileText as t } from './navigation-profile-messages.js';

const semanticIds = new Set(['segformer-b0-ade20k', 'yolo26n-sem-ade20k']);
export const tuningBounds = { pixel_confidence: [.05, 1], min_floor_fraction: [.5, 1],
  max_uncertain_fraction: [0, .5], min_region_fraction: [0, .02] };
const depthBounds = { residual_limit: [.01, .15], outlier_limit: [0, .02], slope_min: [1, 4] };
export function tuningModelId(policy) {
  if (policy?.perception?.model_id) return policy.perception.model_id;
  if (policy?.perception?.engine === 'depth_plane') return 'depth-anything-v2-indoor-small';
  if (policy?.perception?.engine === 'segformer') return 'segformer-b0-ade20k';
  return '';
}
function depthInputValue(key, value) {
  if (value === '') return Number.NaN;
  const scale = key === 'outlier_limit' ? 100 : 1;
  return Number(value) / scale;
}
function tuningErrorKey(error) {
  const code = String(error.data?.error?.code || error.data?.error || error.message || '');
  if (/conflict|changed/.test(code)) return 'behavior.conflict';
  if (/stop_goals|stop_loops/.test(code)) return 'behavior.block.observation';
  if (/active|idle|motion|stopped/.test(code)) return 'behavior.block.motion';
  return 'tuning.failed';
}
export function semanticTuning(perception, id) {
  const row = perception?.semantic_models?.[id] || {};
  return { version: 1, surface: row.surface === 'floor_rug' ? 'floor_rug' : 'floor_only',
    ...Object.fromEntries(Object.keys(tuningBounds).map(key => [key, typeof row[key] === 'number' ? row[key] : null])) };
}
export function validTuning(perception, id) {
  const semantic = semanticIds.has(id);
  if (!semantic && perception?.engine !== 'depth_plane') return false;
  const values = semantic ? semanticTuning(perception, id) : perception;
  return Object.entries(semantic ? tuningBounds : depthBounds).every(([key, [low, high]]) =>
    semantic && values[key] === null || typeof values[key] === 'number' && Number.isFinite(values[key]) && values[key] >= low && values[key] <= high);
}
export class ModelTuning {
  constructor(safety) {
    this.safety = safety; this.policy = null; this.status = null; this.pipeline = null; this.draft = null; this.editBase = null;
    this.busy = false; this.epoch = 0; this.error = ''; this.saved = null;
    const capture = () => { if (!this.draft) this.editBase = this.base(); };
    const surface = document.getElementById('model-tuning-surface');
    surface?.addEventListener('focus', capture);
    surface?.addEventListener('change', () => this.editSemantic('surface', surface.value));
    for (const key of Object.keys(tuningBounds)) {
      const mode = document.getElementById('model-tuning-mode-' + key), input = document.getElementById('model-tuning-' + key);
      mode?.addEventListener('focus', capture); input?.addEventListener('focus', capture);
      mode?.addEventListener('change', () => this.editSemantic(key, mode.value === 'inherit' ? null : this.effective()?.[key] ?? Number.NaN));
      input?.addEventListener('input', () => this.editSemantic(key, input.value === '' ? Number.NaN : Number(input.value)));
    }
    for (const key of Object.keys(depthBounds)) {
      const input = document.getElementById('model-tuning-' + key);
      input?.addEventListener('focus', capture);
      input?.addEventListener('input', () => this.edit(current => ({ ...current,
        [key]: depthInputValue(key, input.value) })));
    }
    document.getElementById('model-tuning-apply')?.addEventListener('click', () => void this.apply());
    document.getElementById('model-tuning-refresh')?.addEventListener('click', () => void this.refresh());
    this.poller = poll(() => this.load(), { interval: 3000, onError: () => {
      this.policy = null; this.status = null; this.pipeline = null; this.error = 'behavior.block.stale'; this.render();
    } });
    window.addEventListener('dashboard:langchange', () => this.render()); this.render();
  }
  base() {
    return { revision: this.policy?.revision, modelId: tuningModelId(this.policy),
      generation: this.safety?.state?.generation, pipelineRevision: this.pipeline?.revision, provider: this.pipeline?.profile?.analysis_location, perception: structuredClone(this.policy?.perception || {}) };
  }
  stale() {
    const base = this.base();
    return !!this.draft && ['revision', 'modelId', 'generation', 'pipelineRevision', 'provider'].some(key => this.draft[key] !== base[key]);
  }
  effective() {
    const row = this.policy?.perception_tuning;
    return row?.version === 1 && row.active_model_id === tuningModelId(this.policy) ? row.effective : null;
  }
  edit(change) {
    const base = this.draft || this.editBase || this.base();
    if (!base.modelId || base.modelId !== tuningModelId(this.policy)) return;
    this.draft = { ...base, perception: change(base.perception) }; this.error = ''; this.saved = null; this.render();
  }
  editSemantic(key, value) {
    this.edit(current => ({ ...current, semantic_models: { ...current.semantic_models,
      [tuningModelId(this.policy)]: { ...semanticTuning(current, tuningModelId(this.policy)), [key]: value } } }));
  }
  supported() {
    const id = tuningModelId(this.policy);
    return this.pipeline?.profile?.analysis_location === 'venom' && (semanticIds.has(id) ? this.policy?.model_tuning_supported === true : this.policy?.perception?.engine === 'depth_plane');
  }
  blocked() {
    if (this.pipeline?.profile?.analysis_location === 'local') return 'tuning.local';
    if (this.pipeline?.profile?.analysis_location !== 'venom') return 'tuning.providerUnknown';
    if (!this.supported()) return 'tuning.unsupported';
    if (this.stale()) return 'behavior.conflict';
    const safety = this.safety?.state;
    if (!safety || safety.stale === true || !['ARMED', 'DISARMED', 'ESTOP'].includes(safety.state)
      || this.safety.clockFresh?.() !== true) return 'behavior.block.stale';
    if (safety.moving === true || ['active', 'qualifying'].includes(safety.operator_control?.state)
      || this.status?.running === true && this.status?.mode === 'drive') return 'behavior.block.motion';
    if (this.status?.running === true) return 'behavior.block.observation';
    return this.busy ? 'behavior.block.busy' : '';
  }
  async load() {
    if (this.busy) return;
    const epoch = this.epoch;
    const [policy, status, pipeline] = await Promise.all([request('/api/navigation/config'), request('/api/navigation/status'), request('/api/resource/camera/pipeline')]);
    if (epoch !== this.epoch || this.busy) return;
    this.policy = policy.data; this.status = status.data; this.pipeline = pipeline.data; this.render();
  }
  currentModelLabel(id, host) {
    if (this.pipeline?.profile?.analysis_location === 'local') return 'Rider-Pi · ' + (this.pipeline.profile.local_engine || '—');
    if (host) return id || '—';
    return t('tuning.providerUnknown');
  }
  renderSurface(row) {
    const surface = document.getElementById('model-tuning-surface');
    if (!surface) return;
    surface.value = row.surface; surface.disabled = !this.supported() || this.busy;
    for (const option of surface.options || []) option.textContent = t(option.value === 'floor_rug' ? 'tuning.floorRug' : 'tuning.floorOnly');
  }
  renderSemanticMode(key, value) {
    const mode = document.getElementById('model-tuning-mode-' + key);
    if (!mode) return;
    mode.value = value === null ? 'inherit' : 'custom'; mode.disabled = !this.supported() || this.busy;
    for (const option of mode.options || []) option.textContent = t(option.value === 'inherit' ? 'tuning.inherit' : 'tuning.custom');
  }
  renderSemanticField(key, row, effective) {
    text('model-tuning-label-' + key, t('tuning.' + key));
    this.renderSemanticMode(key, row[key]);
    const input = document.getElementById('model-tuning-' + key);
    if (!input) return;
    input.disabled = !this.supported() || this.busy || row[key] === null;
    input.placeholder = effective?.[key] === undefined ? '—' : String(effective[key]);
    input.setAttribute?.('aria-label', t('tuning.' + key));
    if (document.activeElement !== input) input.value = row[key] === null || !Number.isFinite(row[key]) ? '' : row[key];
  }
  renderDepthField(key, current, depth) {
    text('model-tuning-label-' + key, t('tuning.' + key));
    const input = document.getElementById('model-tuning-' + key);
    if (!input) return;
    input.disabled = !depth || this.busy;
    if (document.activeElement === input) return;
    const scale = key === 'outlier_limit' ? 100 : 1;
    input.value = Number.isFinite(current[key]) ? current[key] * scale : '';
  }
  message(block, current, id) {
    if (this.error || block) return t(this.error || block, { model: this.pipeline?.profile?.local_engine || '—' });
    if (this.draft && !validTuning(current, id)) return t('tuning.invalid');
    if (this.saved === this.policy?.revision) return t('tuning.saved', { revision: this.saved });
    return '';
  }
  renderActions(block, current, id) {
    const changed = this.draft && JSON.stringify(this.draft.perception) !== JSON.stringify(this.policy?.perception);
    const apply = document.getElementById('model-tuning-apply'), refresh = document.getElementById('model-tuning-refresh');
    if (apply) { apply.textContent = t(this.busy ? 'behavior.saving' : 'tuning.apply'); apply.disabled = !changed || !!block || !validTuning(current, id); }
    if (refresh) { refresh.textContent = t(this.draft ? 'behavior.discard' : 'behavior.refresh'); refresh.disabled = this.busy; }
  }
  renderSections(semantic, depth) {
    for (const kind of ['semantic','depth']) {
      const section = document.getElementById('model-tuning-' + kind);
      if (section) section.hidden = kind === 'semantic' ? !semantic : !depth;
    }
  }
  render() {
    const id = tuningModelId(this.policy), host = this.pipeline?.profile?.analysis_location === 'venom', semantic = host && semanticIds.has(id), depth = host && this.policy?.perception?.engine === 'depth_plane';
    for (const [node, key] of [['title','title'], ['hint','hint'], ['surface-label','surface'], ['rug-hint','rugHint'],
      ['semantic-label','semantic'], ['depth-label','depth'], ['effective-label','effective']]) text('model-tuning-' + node, t('tuning.' + key));
    text('model-tuning-current', t('tuning.current', { model: this.currentModelLabel(id, host), revision: this.policy?.revision ?? '—' }));
    this.renderSections(semantic, depth);
    const current = this.draft?.modelId === id ? this.draft.perception : this.policy?.perception || {};
    const row = semanticTuning(current, id), effective = this.effective();
    this.renderSurface(row);
    for (const key of Object.keys(tuningBounds)) this.renderSemanticField(key, row, effective);
    for (const key of Object.keys(depthBounds)) this.renderDepthField(key, current, depth);
    text('model-tuning-effective', host && effective ? JSON.stringify(effective, null, 2) : '—');
    const block = this.blocked();
    text('model-tuning-draft', this.draft ? t('tuning.pending') : '');
    text('model-tuning-message', this.message(block, current, id));
    this.renderActions(block, current, id);
  }
  readyToApply(block, id) {
    if (this.draft && !block && validTuning(this.draft.perception, id)) return true;
    if (block) { this.error = block; this.render(); }
    return false;
  }
  async refresh() {
    if (this.busy) return;
    this.draft = null; this.editBase = null; this.error = ''; this.saved = null; this.render();
    await this.poller.refresh();
  }
  async apply() {
    const block = this.blocked(), id = tuningModelId(this.policy);
    if (!this.readyToApply(block, id)) return;
    if (JSON.stringify(this.draft.perception) === JSON.stringify(this.policy.perception)) return;
    const draft = this.draft;
    this.busy = true; this.epoch++; this.error = ''; this.saved = null; this.render();
    try {
      const response = await request('/api/navigation/config', { method: 'POST', body: {
        revision: draft.revision, values: { perception: draft.perception },
      } });
      const config = response.data?.config || response.data;
      if (!Number.isSafeInteger(config?.revision)) throw new Error('model_tuning_response_invalid');
      this.policy = config; this.draft = null; this.editBase = null; this.saved = config.revision;
    } catch (error) {
      this.error = tuningErrorKey(error);
      showError(new Error(t(this.error)));
    } finally {
      this.epoch++; this.busy = false; this.render();
      try { await this.load(); } catch { this.error ||= 'behavior.block.stale'; this.render(); }
    }
  }
}
