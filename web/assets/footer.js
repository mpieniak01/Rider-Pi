(function () {
  const targets = Array.from(document.querySelectorAll('[data-dashboard-footer-target]'));
  if (!targets.length) {
    return;
  }

  const pendingQueue = Array.isArray(window.__footerPending)
    ? window.__footerPending.slice()
    : [];
  delete window.__footerPending;

  loadTemplate()
    .then((html) => {
      const contexts = targets
        .map((target) => {
          target.innerHTML = html;
          target.classList.add('footer-ready');
          const root = target.querySelector('[data-footer-root]') || target;
          return {
            root,
            presencePill: root.querySelector('[data-footer-presence]'),
            presenceState: root.querySelector('[data-footer-presence-state]'),
            modeEl: root.querySelector('[data-footer-mode]'),
            modeLabel: extractLabel(root.querySelector('[data-footer-mode]'), 'mode'),
            confEl: root.querySelector('[data-footer-conf]'),
            confLabel: extractLabel(root.querySelector('[data-footer-conf]'), 'conf'),
            camEl: root.querySelector('[data-footer-camera]'),
            camLabel: extractLabel(root.querySelector('[data-footer-camera]'), 'CAM'),
            camMetaEl: root.querySelector('[data-footer-camera-meta]'),
            camMetaLabel: extractLabel(root.querySelector('[data-footer-camera-meta]'), 'fps'),
            themeSelect: root.querySelector('[data-footer-theme-select]'),
          };
        })
        .filter(Boolean);

      setupThemeSwitcher(contexts);
      setupUpdateBridge(contexts, pendingQueue);
    })
    .catch((err) => {
      console.error('Nie udało się przygotować stopki:', err);
      targets.forEach((target) => {
        target.innerHTML = '<div class="footer-error">Błąd ładowania stopki</div>';
      });
    });

  function loadTemplate() {
    return fetch('/web/dashboard_footer_template.html', { cache: 'no-store' })
      .then((res) => {
        if (!res.ok) {
          throw new Error('Footer HTTP ' + res.status);
        }
        return res.text();
      })
      .catch((err) => {
        console.warn('Używam awaryjnej wersji stopki:', err);
        return getInlineTemplate();
      });
  }

  function getInlineTemplate() {
    return `
<div class="c-statusbar" data-footer-root>
  <span class="c-pill" data-footer-presence>
    <span>VISION:</span>&nbsp;
    <span data-footer-presence-state>—</span>
  </span>
  <span class="u-sep">•</span>
  <span class="muted" data-footer-mode>mode: —</span>
  <span class="u-sep">•</span>
  <span class="muted" data-footer-conf>conf: —</span>
  <span class="u-sep">•</span>
  <span class="c-pill" data-footer-camera>CAM: —</span>
  <span class="muted" data-footer-camera-meta>fps: —</span>
  <span class="u-sep">•</span>
  <label class="footer-theme">
    <span>Motyw</span>
    <select data-footer-theme-select>
      <option value="classic">Klasyczny</option>
      <option value="classic-plus">Klasyczny +</option>
      <option value="v2">Tryb V2</option>
      <option value="v3">Neo (v3)</option>
    </select>
  </label>
  <span class="u-spacer"></span>
  <span class="footer-version">
    <span class="footer-version__label">Wersja</span>
    <span class="footer-version__branch">—</span>
    <button type="button" class="footer-version__commit" disabled>#unknown</button>
  </span>
</div>
`.trim();
  }

  function extractLabel(el, fallback) {
    if (!el) return fallback;
    const text = el.textContent || '';
    const idx = text.indexOf(':');
    if (idx === -1) {
      return text.trim() || fallback;
    }
    return text.slice(0, idx).trim() || fallback;
  }

  function setupThemeSwitcher(contexts) {
    const selects = contexts
      .map((ctx) => ctx.themeSelect)
      .filter((el) => el);
    if (!selects.length) {
      return;
    }
    const themeApi = window.dashboardTheme || null;
    const knownThemes =
      themeApi?.options?.map((o) => o.value) || ['classic', 'classic-plus', 'v2', 'v3'];
    const normalize = (value) => (knownThemes.includes(value) ? value : 'classic');
    const syncSelects = (value, source) => {
      selects.forEach((sel) => {
        if (sel !== source) {
          sel.value = value;
        }
      });
    };

    const currentTheme =
      themeApi?.get?.() || document.documentElement.getAttribute('data-dashboard-theme') || 'classic';
    selects.forEach((select) => {
      select.value = normalize(currentTheme);
      select.addEventListener('change', () => {
        const chosen = normalize(select.value);
        if (themeApi?.set) {
          themeApi.set(chosen);
        } else {
          document.documentElement.setAttribute('data-dashboard-theme', chosen);
        }
        syncSelects(chosen, select);
      });
    });
  }

  function setupUpdateBridge(contexts, pendingQueue) {
    if (!contexts.length) {
      return;
    }

    const footerState = {
      state: null,
      snapInfo: null,
      cameraResource: null,
    };

    const render = () => {
      contexts.forEach((ctx) => {
        renderPresence(ctx, footerState.state);
        renderCamera(ctx, footerState.state, footerState.snapInfo, footerState.cameraResource);
      });
    };

    const update = (partial = {}) => {
      let changed = false;
      if (Object.prototype.hasOwnProperty.call(partial, 'state')) {
        footerState.state = partial.state || null;
        changed = true;
      }
      if (Object.prototype.hasOwnProperty.call(partial, 'snapInfo')) {
        footerState.snapInfo = partial.snapInfo || null;
        changed = true;
      }
      if (Object.prototype.hasOwnProperty.call(partial, 'cameraResource')) {
        footerState.cameraResource = partial.cameraResource || null;
        changed = true;
      }
      if (changed) {
        render();
      }
    };

    window.dashboardFooter = { update };
    pendingQueue.forEach((payload) => {
      try {
        update(payload || {});
      } catch (err) {
        console.warn('Nie udało się zastosować oczekującej aktualizacji stopki:', err);
      }
    });
  }

  function renderPresence(ctx, state) {
    if (!ctx.presencePill || !ctx.presenceState || !ctx.modeEl || !ctx.confEl) {
      return;
    }
    const present = Boolean(state?.present);
    ctx.presencePill.className = 'c-pill ' + (present ? 'ok' : 'off');
    ctx.presenceState.textContent = present ? 'ACTIVE' : 'IDLE';
    const modeValue = state?.mode || '—';
    ctx.modeEl.textContent = `${ctx.modeLabel}: ${modeValue}`;
    const confValue = state?.confidence != null ? Number(state.confidence).toFixed(3) : '—';
    ctx.confEl.textContent = `${ctx.confLabel}: ${confValue}`;
  }

  function renderCamera(ctx, state, snapInfo, cameraResource) {
    if (!ctx.camEl || !ctx.camMetaEl) {
      return;
    }
    const rawAge = snapInfo?.raw?.age_s;
    const procAge = snapInfo?.proc?.age_s;
    const trackerAge = snapInfo?.tracker?.age_s;
    const rawTxt = formatAge(rawAge);
    const procTxt = formatAge(procAge);
    const trackerTxt = formatAge(trackerAge);
    ctx.camEl.textContent = `${ctx.camLabel}: ${rawTxt} / ${procTxt} • TRK: ${trackerTxt}`;
    const cameraOk = isCameraOnline(state);
    ctx.camEl.className = 'c-pill ' + (cameraOk ? 'ok' : 'off');

    const metaParts = [];
    const fps = state?.camera?.fps;
    if (typeof fps === 'number' && !Number.isNaN(fps)) {
      metaParts.push(`${fps.toFixed(1)} fps`);
    }
    const holdersText = describeCameraResource(cameraResource);
    if (holdersText) {
      metaParts.push(holdersText);
    }
    const metaValue = metaParts.length ? metaParts.join(' • ') : '—';
    ctx.camMetaEl.textContent = `${ctx.camMetaLabel}: ${metaValue}`;
  }

  function isCameraOnline(state) {
    if (!state || !state.camera) {
      return false;
    }
    if (state.camera.vision_enabled === false) {
      return false;
    }
    if (state.camera.on === false) {
      return false;
    }
    return true;
  }

  function formatAge(value) {
    if (value == null || Number.isNaN(Number(value))) {
      return '—';
    }
    return `${Number(value).toFixed(1)}s`;
  }

  function describeCameraResource(resource) {
    if (!resource) {
      return '';
    }
    if (resource.error) {
      return `err: ${resource.error}`;
    }
    if (resource.free) {
      return 'free';
    }
    if (Array.isArray(resource.holders) && resource.holders.length) {
      const holders = resource.holders
        .map((holder) => {
          const cmd = holder?.cmd || holder?.command || 'proc';
          const pid = holder?.pid != null ? holder.pid : '?';
          const svc = holder?.service ? `:${holder.service}` : '';
          return `${cmd}#${pid}${svc}`;
        })
        .join(', ');
      return `hold: ${holders}`;
    }
    return '';
  }
})();
