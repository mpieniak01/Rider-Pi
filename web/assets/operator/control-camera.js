import { request, poll } from './transport.js';
import { cameraFrame } from './model.js';
import { text, tr } from './ui.js';

// Only GET snapshots; mounting this panel never starts a camera or an actuator.
export class ControlCamera {
  constructor() {
    this.kind = 'raw'; this.auto = true; this.meta = null; this.busy = false;
    this.loaded = null; this.pending = null; this.lastKey = null; this.failed = false;
    this.image = document.getElementById('control-camera-image');
    this.empty = document.getElementById('control-camera-empty');
    for (const id of ['speed', 'yaw-speed']) {
      const input = document.getElementById(id);
      const update = () => text(id + '-value', Number(input.value).toFixed(2));
      input?.addEventListener('input', update); if (input) update();
    }
    this.image.addEventListener('load', () => {
      this.loaded = this.pending; this.pending = null; this.busy = false;
      this.failed = false; clearTimeout(this.timeout); this.render();
    });
    this.image.addEventListener('error', () => this.fail());
    document.getElementById('control-camera-toggle').addEventListener('click', () => {
      this.auto = !this.auto; this.render(); if (this.auto) this.poller.refresh();
    });
    document.querySelectorAll('[data-camera-kind]').forEach(button => button.addEventListener('click', () => {
      this.kind = button.dataset.cameraKind; this.cancel(); this.loaded = null;
      this.lastKey = null; this.render(); this.poller.refresh();
    }));
    this.poller = poll(async () => {
      if (!this.auto) return;
      try { this.meta = (await request('/vision/snap-info?light=1')).data; }
      catch { this.meta = null; }
      this.render(); this.frame();
    }, { interval: 1000, onVisibility: hidden => { if (hidden) this.cancel(); } });
    this.expiry = setInterval(() => { if (!document.hidden) this.render(); }, 500);
    window.addEventListener('dashboard:langchange', () => this.render());
    window.addEventListener('pagehide', () => { this.poller.stop(); clearInterval(this.expiry); this.cancel(); });
  }
  cancel() {
    clearTimeout(this.timeout); this.pending = null; this.busy = false; this.lastKey = null; this.loaded = null;
    this.image.removeAttribute('src');
  }
  fail() {
    this.cancel(); this.loaded = null; this.lastKey = null; this.failed = true; this.render();
  }
  render() {
    const frame = cameraFrame(this.meta, this.kind);
    const loaded = cameraFrame({ shown: { exists: !!this.loaded, observed_at: this.loaded?.ts } }, 'shown');
    const current = frame.fresh && loaded.fresh && this.loaded?.kind === this.kind;
    this.image.hidden = !current; this.empty.hidden = current;
    text('control-camera-toggle', this.auto ? tr('⟳ Auto: włączone', '⟳ Auto: on') : tr('⟳ Auto: wyłączone', '⟳ Auto: off'));
    text('control-camera-status', this.kind.toUpperCase() + ' · ' +
      (current ? tr('bieżąca klatka', 'current frame') : this.failed ? tr('błąd odczytu klatki', 'frame load failed') : tr('brak / stary obraz', 'missing / stale image')) +
      ' · ' + (loaded.age === null ? '—' : loaded.age.toFixed(1) + ' s') +
      (frame.timeBasis === 'file' ? tr(' · wiek pliku; czas przechwycenia niepotwierdzony', ' · file age; capture time unverified') : ''));
    document.querySelectorAll('[data-camera-kind]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.cameraKind === this.kind)));
  }
  frame() {
    if (!this.auto || this.busy || document.hidden) return;
    const frame = cameraFrame(this.meta, this.kind);
    if (!frame.fresh) return;
    const key = this.kind + ':' + frame.ts;
    if (key === this.lastKey) return;
    this.lastKey = key; this.busy = true; this.pending = { kind: this.kind, ts: frame.ts };
    this.image.src = (this.kind === 'proc' ? '/vision/edge' : '/vision/cam') + '?t=' + encodeURIComponent(frame.ts);
    this.timeout = setTimeout(() => this.fail(), 6000);
  }
}
