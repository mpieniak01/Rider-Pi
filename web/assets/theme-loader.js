(function () {
  const STORAGE_KEY = 'dashboard_theme';
  const THEMES = ['classic', 'classic-plus', 'v2', 'v3'];
  const DEFAULT_THEME = 'classic';
  let domReady = false;

  function normalizeTheme(value) {
    if (typeof value !== 'string') return DEFAULT_THEME;
    const clean = value.toLowerCase();
    return THEMES.includes(clean) ? clean : DEFAULT_THEME;
  }

  function syncThemeLinks(theme) {
    if (!domReady && document.readyState === 'loading') {
      document.addEventListener(
        'DOMContentLoaded',
        () => {
          domReady = true;
          syncThemeLinks(theme);
        },
        { once: true }
      );
      return;
    }
    domReady = true;
    document.querySelectorAll('link[data-theme-skin]').forEach((link) => {
      const targets = (link.dataset.themeSkin || '').split(',').map((t) => t.trim());
      link.disabled = !targets.includes(theme);
    });
    document.querySelectorAll('link[data-theme-page]').forEach((link) => {
      const targets = (link.dataset.themePage || '').split(',').map((t) => t.trim());
      link.disabled = !targets.includes(theme);
    });
  }

  function applyTheme(theme, { persist = true } = {}) {
    const normalized = normalizeTheme(theme);
    document.documentElement.setAttribute('data-dashboard-theme', normalized);
    syncThemeLinks(normalized);
    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, normalized);
      } catch (err) {
        console.warn('Nie mogę zapisać motywu w localStorage:', err);
      }
    }
    return normalized;
  }

  function init() {
    let storedTheme = null;
    try {
      storedTheme = localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      console.warn('Brak dostępu do localStorage (motywy):', err);
    }
    applyTheme(storedTheme || DEFAULT_THEME, { persist: false });
  }

  init();

  window.dashboardTheme = {
    get: () => document.documentElement.getAttribute('data-dashboard-theme') || DEFAULT_THEME,
    set: (theme) => applyTheme(theme),
    options: [
      { value: 'classic', label: 'Klasyczny' },
      { value: 'classic-plus', label: 'Klasyczny +' },
      { value: 'v2', label: 'Tryb V2' },
      { value: 'v3', label: 'Neo (v3)' },
    ],
  };
})();
