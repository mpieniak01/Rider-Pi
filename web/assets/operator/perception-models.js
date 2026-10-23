import { request, poll } from './transport.js';
import { requestId } from './request-id.js';
import { tr, text, showError } from './ui.js';
import { validPipeline } from './camera-pipeline.js';

/** One Pi camera profile and one host model identity; no installation on Pi. */
export class PerceptionModels {
  constructor(safety) {
    this.safety = safety; this.busy = false; this.epoch = 0;
    document.getElementById('perception-refresh')?.addEventListener('click', () => this.poller.refresh());
    document.getElementById('perception-provider-apply')?.addEventListener('click', () => void this.applyProvider());
    document.getElementById('perception-model-apply')?.addEventListener('click', () => void this.applyModel());
    this.poller = poll(() => this.load(), { interval: 3000, onError: error => {
      this.pipeline = null; this.policy = null; this.host = null; this.local = null;
      this.error = error.message; this.render();
    } });
    window.addEventListener('dashboard:langchange', () => this.render());
    this.render();
  }
  async load() {
    if (this.busy) return;
    const epoch = this.epoch;
    const [pipeline, policy, local, host] = await Promise.allSettled([
      request('/api/resource/camera/pipeline'), request('/api/navigation/config'),
      request('/api/navigation/local-models'), request('/api/navigation/models'),
    ]);
    if (epoch !== this.epoch || this.busy) return;
    if (pipeline.status !== 'fulfilled' || !validPipeline(pipeline.value.data)) {
      throw new Error('camera_pipeline_status_unavailable');
    }
    this.pipeline = pipeline.value.data;
    this.policy = policy.status === 'fulfilled' ? policy.value.data : null;
    this.local = local.status === 'fulfilled' ? local.value.data : null;
    this.host = host.status === 'fulfilled' ? host.value.data : null;
    this.error = host.status === 'rejected' ? host.reason.message : '';
    this.render();
  }
  choices(id, rows, selected) {
    const select = document.getElementById(id);
    if (!select) return;
    const key = JSON.stringify([rows, selected]);
    if (select.dataset.choices !== key && document.activeElement !== select) {
      select.dataset.choices = key;
      select.replaceChildren(...rows.map(([value, label, supported]) => {
        const option = document.createElement('option');
        option.value = value; option.textContent = label; option.disabled = !supported;
        option.selected = value === selected; return option;
      }));
    }
    select.disabled = this.busy || !this.pipeline;
  }
  modelRows() {
    return this.pipeline?.profile.analysis_location === 'local' ? this.local?.models : this.host?.models;
  }
  render() {
    const provider = this.pipeline?.profile.analysis_location;
    const local = provider === 'local';
    const rows = this.modelRows() || [];
    this.choices('perception-provider', [
      ['venom', 'Venom', this.pipeline?.capabilities.analysis_locations.includes('venom')],
      ['local', tr('Lokalnie na Rider-Pi', 'Local on Rider-Pi'), this.pipeline?.capabilities.analysis_locations.includes('local')],
    ], provider);
    const selected = local ? this.local?.selected_model_id
      : this.host?.selection?.model_id || this.policy?.perception?.model_id;
    this.choices('perception-model', rows.map(row => [
      row.id, row.label + ' · ' + row.installation + (row.reason ? ' · ' + row.reason : ''),
      row.selectable === true && row.installation === 'ready',
    ]), selected);
    const runtime = this.host?.diagnostics?.runtime;
    const active = local ? this.local?.active_model_id
      : runtime?.state === 'ready' || runtime?.state === 'loaded' ? runtime.active_model_id : null;
    text('perception-selected', tr('Wybrany: ', 'Selected: ') + (selected || tr('profil historyczny', 'legacy profile')));
    text('perception-active', tr('Aktywny: ', 'Active: ') + (active || tr('brak potwierdzonego wyniku', 'no confirmed result')));
    text('perception-state', provider ? provider + ' · r' + this.pipeline.revision : tr('Stan nieznany', 'Unknown state'));
    text('perception-error', this.error || '');
    const armed = this.safety?.state?.state === 'ARMED';
    const providerButton = document.getElementById('perception-provider-apply');
    const modelButton = document.getElementById('perception-model-apply');
    if (providerButton) providerButton.disabled = this.busy || !this.pipeline || armed;
    if (modelButton) modelButton.disabled = this.busy || !this.pipeline || armed || !this.policy
      || (local ? !this.local : !this.host || this.host.switching === true) || !rows.some(row => row.selectable === true);
  }
  async mutate(action) {
    if (this.busy || !this.pipeline) return;
    this.busy = true; this.epoch++; this.error = ''; this.render();
    try { await action(); }
    catch (error) { this.error = error.message; showError(error); }
    finally { this.epoch++; this.busy = false; this.render(); void this.poller.refresh(); }
  }
  async configureProfile(profile) {
    await request('/api/resource/camera/pipeline', { method: 'POST', timeout: 20000, body: {
      contract_version: 1, request_id: requestId('perception'), expected_revision: this.pipeline.revision,
      action: 'configure', profile,
    } });
  }
  async applyProvider() {
    const value = document.getElementById('perception-provider')?.value;
    if (!['local', 'venom'].includes(value)) return;
    if (!this.pipeline?.capabilities.analysis_locations.includes(value)) return;
    if (value === this.pipeline.profile.analysis_location) return;
    await this.mutate(() => this.configureProfile({ ...this.pipeline.profile, analysis_location: value }));
  }
  async applyModel() {
    const id = document.getElementById('perception-model')?.value;
    const row = this.modelRows()?.find(item => item.id === id);
    if (!row || row.selectable !== true || row.installation !== 'ready' || !this.policy) return;
    await this.mutate(async () => {
      if (this.pipeline.profile.analysis_location === 'local') {
        await this.configureProfile({ ...this.pipeline.profile, local_engine: row.engine });
      } else {
        await request('/api/navigation/model', { method: 'POST', timeout: 20000,
          body: { revision: this.policy.revision, model_id: row.id } });
      }
    });
  }
}
