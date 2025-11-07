(function(){
  const target = document.querySelector('[data-dashboard-menu-target]');
  if (!target) return;

  fetch('/web/dashboard_menu_template.html', { cache: 'no-store' })
    .then(res => {
      if (!res.ok) throw new Error('Menu HTTP ' + res.status);
      return res.text();
    })
    .then(html => {
      target.innerHTML = html;
      target.classList.add('menu-ready');
      const nav = target.querySelector('.dashboard-menu');
      if (!nav) return;
      setupMenu(nav);
      if (window.i18n?.applyDom) {
        window.i18n.applyDom(target);
      }
    })
    .catch(err => {
      console.error('Nie udało się wczytać menu:', err);
      target.innerHTML = '<div class="menu-error">Błąd ładowania menu</div>';
    });

  function setupMenu(nav){
    const pagePriority = nav.dataset.active || document.body.dataset.page;
    const links = Array.from(nav.querySelectorAll('a[data-page]'));

    highlightActive(links, pagePriority);
    initToggle(nav);
    initLangSwitch(nav);
  }

  function highlightActive(links, preferred){
    if (!links.length) return;

    const normalize = (path) => (path.replace(/\/+$/, '') || '/');
    let active = null;

    if (preferred){
      active = links.find(link => link.dataset.page === preferred);
    }
    if (!active){
      const current = normalize(window.location.pathname || '');
      active = links.find(link => normalize(new URL(link.href, window.location.origin).pathname) === current);
    }
    active?.classList.add('is-active');
  }

  function initToggle(nav){
    const toggle = nav.querySelector('.menu-toggle');
    if (!toggle) return;
    toggle.addEventListener('click', () => {
      const isOpen = nav.classList.toggle('menu-open');
      toggle.setAttribute('aria-expanded', String(isOpen));
    });
  }

  function initLangSwitch(nav){
    const container = nav.querySelector('.lang-switch');
    if (!container) return;
    const buttons = Array.from(container.querySelectorAll('button[data-lang]'));
    if (!buttons.length) return;

    const normalize = (lang) => (lang && lang.toLowerCase().startsWith('en')) ? 'en' : 'pl';
    const stored = normalize(localStorage.getItem('lang') || document.documentElement.getAttribute('lang') || navigator.language);

    updateButtons(stored);

    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const lang = normalize(btn.dataset.lang);
        applyLanguage(lang);
      });
    });

    window.addEventListener('dashboard:langchange', (ev) => {
      const lang = normalize(ev?.detail?.lang);
      updateButtons(lang);
    });

    function updateButtons(lang){
      buttons.forEach(btn => {
        const active = normalize(btn.dataset.lang) === lang;
        btn.setAttribute('aria-pressed', String(active));
      });
    }

    function emitLang(lang){
      if (typeof CustomEvent === 'function') {
        window.dispatchEvent(new CustomEvent('dashboard:langchange', { detail: { lang } }));
      } else if (document && typeof document.createEvent === 'function') {
        const evt = document.createEvent('CustomEvent');
        evt.initCustomEvent('dashboard:langchange', false, false, { lang });
        window.dispatchEvent(evt);
      }
    }

    function applyLanguage(lang){
      localStorage.setItem('lang', lang);
      updateButtons(lang);
      if (window.i18n?.setLang) {
        window.i18n.setLang(lang);
      } else {
        document.documentElement?.setAttribute('lang', lang);
        emitLang(lang);
      }
    }
  }
})();
