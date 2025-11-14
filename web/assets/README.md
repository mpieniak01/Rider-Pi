# Web Style Inventory & Migration Plan

This repository currently styles each dashboard page with its own CSS file. `dashboard-common.css`
contains only a fraction of the shared rules, so layout primitives exist in several places with
subtle differences. The goal of this document is to capture the current state, highlight overlaps,
and outline the path toward a single shared “framework” layer.

## 1. Inventory Snapshot

| CSS file                  | Primary pages               | Key layout / component selectors                                                                                  | Notes                                                   |
|---------------------------|-----------------------------|--------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------|
| `dashboard-common.css`    | `control` (+ menu partial)  | `.wrap`, `.card`, `.pill`, `.btn`, `.svc-desc-*`, `.svc-state-*`, `.dashboard-menu`, `.brand`, `.lang-switch`      | Defines tokens (`--bg`, `--pad`, …) but only some views |
| `control.css`             | `control.html`              | `.wrap`, `.panel-row`, `.row`, `.grid`, `.card`, `.btn-sm`, `.pill`, `.svc-table`, `.feature-*`, `.resource-card`  | Full layout + component stack duplicated elsewhere      |
| `chat.css`                | `chat.html`                 | `.wrap`, `.row`, `.btn`, `.btn-sm`, `.pill`, `.providers-*`, `.msg`, `.status`                                     | Own palette + button/pill redefinitions                 |
| `google-home.css`         | `google_home.html`          | `.wrap`, `.row`, `.card`, `.device-grid`, `.device-card`, `.btn-sm`, `.pill`, `.status-msg`, `.spinner`            | Many utilities shared with home/control                 |
| `home.css`                | `home.html`                 | `.wrap`, `.row`, `.card`, `.pill`, `.spinner`, `.data-*`                                                           | Mostly dashboard overview cards                         |
| `view.css`                | `view.html`                 | `.wrap`, `.card`, `.grid`, `.legend`, `.statusbar`, `.cam-*`, `.kv`, `.proc`, `.thumb`                             | Video/device monitor layout                             |
| `system.css`              | `system.html`               | `.status-pill`, `.desc`, `.edge-list`, `.system-shell`, `.system-links`                                            | Minimal page-specific styling                           |
| `navigation.css`          | `navigation.html`           | `.legend-item`, `.legend-color` + Tailwind utility classes (`flex`, `bg-gray-900`, …)                               | Inline utility classes, not declared in CSS             |

### Shared selectors across multiple pages

`wrap`, `card`, `row`, `grid`, `btn`, `btn-sm`, `pill`, `muted`, `note`, `hint`, `spacer`, `spinner`,
`ok`, `warn`, `err`, and `status`-style pills appear in at least two HTML files. They are also
redeclared in two or more CSS files, meaning each page picks its own spacing, colors, and typography.

### Page-only selectors

Each screen introduces domains specific selectors (`.provider-*`, `.feature-*`, `.device-*`,
`.statusbar`, `.motion-queue-card`, etc.). These should stay in dedicated modules once they are built
on top of shared primitives.

### Missing / unused definitions

* Several HTML classes (e.g., `feature-pill`, `motion-queue-card`, `service-card`, Tailwind-like
  classes in `navigation.html`) are not declared in any CSS file. They either rely on inline styles
  or are currently unstyled.
* Conversely, there are dozens of CSS-only selectors (e.g., `.bot`, `.provider-row`, `.status-*`,
  numeric timing helpers like `.25`, `.8s`). Many are dead code left from earlier designs.
* An explicit cleanup pass should remove unused selectors once the migration lands.

## 2. Proposed Shared “Framework”

Start by expanding `dashboard-common.css` (or introduce `framework.css`) so every dashboard page
imports it before its page-specific file. The shared layer should include:

* **Design tokens** – root variables for palette, spacing scale, shadows, corner radius, border
  colors, font stack. Keep dashboard-common variables as the single source of truth.
* **Layout primitives** – `.page`/`.wrap` container, generic `.stack` (vertical gap), `.row` (flex),
  `.grid` (CSS grid with `data-grid-cols` attribute helpers), `.section` (panel group), `.spacer` for
  flex layouts, `.scroll-area`, `.status-bar`.
* **Surface patterns** – `.card`, `.card--inline`, `.card--flush`, `.card--interactive` to capture the
  repeated panels on control, home, google-home, and view pages.
* **Typography & utility helpers** – `.muted`, `.label`, `.value`, `.note`, `.hint`, `.kbd`, text size
  utilities, `.text-accent`, `.text-warn`, `.text-err`.
* **Interactive controls** – `.btn`, `.btn-sm`, `.btn-icon`, `.btn-pill`, `.btn-ghost` with shared
  hover/active states and consistent spacing; `.form-control`, `.input`, `.range`.
* **Status affordances** – `.pill`, `.pill--ok`, `.pill--warn`, `.pill--err`, `.status-msg`, `.status-chip`.
* **Grid components** – `.device-grid`, `.legend`, `.legend-item`, `.stat-grid`, `.kv-grid`, `.media-card`.
* **Utility classes** – `.u-flex`, `.u-flex-between`, `.u-align-center`, `.u-gap-sm`, `.u-gap-lg`,
  `.u-hide`, `.u-inline`, `.u-scroll`, `.u-text-center`.

Once these exist, page-specific CSS can focus on paint (provider colors, data viz, etc.) instead of
redeclaring layout rules.

## 3. Naming System

Adopt a lightweight prefix-based convention inspired by BEM:

* `l-…` – layout primitives (e.g., `l-stack`, `l-row`, `l-grid`, `l-sidebar`).
* `c-…` – reusable components (e.g., `c-card`, `c-btn`, `c-pill`, `c-status-msg`, `c-legend-item`).
* `u-…` – one-off utilities (spacing, text color, visibility).
* `is-…` / `has-…` – state modifiers on elements/components (`c-card is-active`, `c-pill is-warn`).
* Page-specific modules keep neutral names but scope inside `body[data-page=\"XYZ\"]` blocks to avoid
  leaks.

Document these prefixes at the top of the shared CSS file so contributors know which bucket to reach
for. For truly composite widgets, use BEM syntax (`c-card__header`, `c-card__footer`, etc.).

## 4. Migration Playbook

1. **Add the framework import** to every HTML page: load `dashboard-common.css`/`framework.css`
   first, then the page module.
2. **Map existing selectors to shared primitives** using the inventory above:
   * Replace local `.wrap`, `.row`, `.card`, `.pill`, `.btn*` definitions with framework classes.
   * Keep page-specific colors by applying modifier classes (`is-provider-openai`, etc.).
3. **Rebuild template markup** gradually:
   * Wrap each logical block in `c-card` or `l-stack` containers.
   * Convert inline Tailwind-like classes in `navigation.html` into equivalent `l-`/`c-` utilities.
4. **Move remaining custom rules** (`.providers-card`, `.device-card`, `.statusbar`) into
   `body[data-page=\"chat\"] …` sections that extend the shared primitives.
5. **Clean up** after each screen:
   * Drop unused selectors from that page’s CSS.
   * Run the class inventory script (`rg -o … | sort -u`) to confirm no regressions.
6. **Guardrails**:
   * Add a Stylelint rule (e.g., `block-no-empty`, `selector-class-pattern`, `no-inline-styles`) and
     wire it into CI.
   * Provide a `npm run lint:css` (or simple `stylelint \"web/**/*.css\"`) command.

## 5. Next Steps

1. Create `framework.css` (or enlarge `dashboard-common.css`) with the primitives listed above.
2. Draft example usage in this README (`Usage` section with snippets) so developers can copy/paste.
3. Migrate one page at a time (recommended order: `home` → `google_home` → `control` → `view`
   → `chat` → `system`), validating responsiveness after each change.
4. Once a page is migrated, remove overlapping selectors from its old CSS file and re-run the
   inventory.

By following this plan we can converge on a consistent dashboard look while keeping page-specific
flair isolated in small, well-documented modules.

## 6. Przykłady użycia

Poniżej szybkie przepisy na często spotykane układy (kopiuj/wklej):

### Karta + lista klucz/wartość

```html
<section class="c-card">
  <h2 class="c-card__title">Status &amp; Metrics</h2>
  <div class="c-kv">
    <div class="muted">State</div><div>ok</div>
    <div class="muted">Last update</div><div>13:45</div>
  </div>
</section>
```

### Grid kart + przyciski nagłówka

```html
<div class="l-grid">
  <article class="c-card cam-card">
    <h3 class="c-card__title">
      Camera
      <button class="c-btn c-btn-sm section-action">⟳</button>
    </h3>
    <div class="c-thumb">
      <img src="/camera" alt="">
    </div>
  </article>
  <article class="c-card">
    <h3 class="c-card__title">Devices</h3>
    <div class="c-legend">
      <span><i class="c-legend__dot ok"></i>Camera</span>
      <span><i class="c-legend__dot warn"></i>LCD</span>
    </div>
  </article>
</div>
```

### Lista tabelaryczna / zasoby

```html
<section class="c-card resource-card">
  <h3 class="c-card__title">Resources</h3>
  <table class="svc-table">
    <thead>
      <tr><th>Name</th><th>Status</th><th>Actions</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>Camera</td>
        <td><span class="c-pill is-ok">OK</span></td>
        <td class="svc-actions">
          <button class="c-btn c-btn-sm">⟳</button>
          <button class="c-btn c-btn-sm">Stop</button>
        </td>
      </tr>
    </tbody>
  </table>
</section>
```

## 7. Co zostało do zrobienia?

- **Navigation/System** – te strony nadal używają lokalnych klas/utility (część wprost tailwindowa); trzeba je przepisać na `c-`/`l-` oraz wyczyścić CSS.
- **Stylelint/checki** – wprowadzić prosty lint (np. `stylelint "web/**/*.css"`) i dodać do CI, aby dokumentował prefixy i blokował inline style.
- **README w przykładach JS** – dodać snippet pokazujący jak w JS zmieniać klasy (`setCls('foo', 'c-pill is-ok')`), by uniknąć powrotu starych nazw.
- **Systematyczny cleanup** – po każdej migracji uruchomić komendę z inwentaryzacją (`rg -o ...`) i kasować nieużywane selektory/stare pliki CSS.
