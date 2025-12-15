# CSS Modules - Rider-PC Dashboard

This directory contains the modular CSS architecture for the Rider-PC dashboard.

## Module Structure

| File | Purpose | Approx. Lines |
|------|---------|---------------|
| `tokens.css` | Design tokens (colors, spacing, typography, shadows) | ~140 |
| `base.css` | CSS reset and foundational element styles | ~180 |
| `layout.css` | Layout systems (grid, flex, page structure) | ~210 |
| `components.css` | Reusable UI components (cards, buttons, pills) | ~460 |
| `utilities.css` | Single-purpose utility classes | ~260 |
| `menu.css` | Navigation menu component | ~180 |
| `footer.css` | Footer/statusbar component | ~95 |

## Legacy Class Mapping

The following table maps legacy classes to their modern equivalents in the modular CSS system.
Legacy classes remain in `dashboard-common.css` for backward compatibility.

### Layout Classes

| Legacy Class | Modern Equivalent | Location |
|--------------|-------------------|----------|
| `.wrap` | `.layout-main` | `layout.css` |
| `.page` | `.layout-main` | `layout.css` |
| `.row` | `.l-row` | `layout.css` |
| `.grid` | `.l-grid` | `layout.css` |
| `.stack` | `.l-stack` | `layout.css` |
| `.panel-row` | `.panel-row` (kept) | `layout.css` |
| `.surface` | `.surface` | `layout.css` |
| `.section` | `.surface` | `layout.css` |

### Component Classes

| Legacy Class | Modern Equivalent | Location |
|--------------|-------------------|----------|
| `.card` | `.c-card` | `components.css` |
| `.card h3` | `.c-card__title` | `components.css` |
| `.pill` | `.c-pill` | `components.css` |
| `.pill.ok` | `.c-pill.is-ok` | `components.css` |
| `.pill.warn` | `.c-pill.is-warn` | `components.css` |
| `.pill.err` | `.c-pill.is-err` | `components.css` |
| `.pill.off` | `.c-pill.is-off` | `components.css` |
| `.btn` | `.c-btn` | `components.css` |
| `.btn-sm` | `.c-btn-sm` | `components.css` |
| `.kv` | `.c-kv` | `components.css` |
| `.thumb` | `.c-thumb` | `components.css` |
| `.statusbar` | `.c-statusbar` | `components.css` |
| `.spinner` | `.c-spinner` | `components.css` |
| `.status-msg` | `.c-status-msg` | `components.css` |
| `.hint` | `.c-hint` | `components.css` |
| `.note` | `.c-note` | `components.css` |
| `.kbd` | `.c-kbd` | `components.css` |
| `.legend` | `.c-legend` | `components.css` |
| `.legend-item` | `.c-legend__item` | `components.css` |
| `.dot` | `.c-legend__dot` | `components.css` |

### Utility Classes

| Legacy Class | Modern Equivalent | Location |
|--------------|-------------------|----------|
| `.muted` | `.u-muted` | `utilities.css` |
| `.ok` | `.u-ok` | `utilities.css` |
| `.warn` | `.u-warn` | `utilities.css` |
| `.err` | `.u-err` | `utilities.css` |
| `.bad` | `.u-bad` | `utilities.css` |
| `.spacer` | `.u-spacer` | `utilities.css` |
| `.sep` | `.u-sep` | `utilities.css` |

### Page-Specific Classes (Kept in dashboard-common.css)

These classes are used by specific pages and have fallback definitions:

| Class | Used By | Description |
|-------|---------|-------------|
| `.control-title` | control.html | Page title with controls |
| `.control-status` | control.html | Status indicator |
| `.control-badge` | control.html | Status badge |
| `.ai-mode-row` | control.html | AI mode controls row |
| `.ai-mode-actions` | control.html | AI mode action buttons |
| `.cam-frame` | control.html | Camera preview frame |
| `.motion-btn` | control.html | Motion control buttons |
| `.svc-select` | control.html | Service select dropdown |
| `.feature-resource` | control.html | Feature/resource section |
| `.system-shell` | system.html | System page container |
| `.models-shell` | models.html | Models page container |
| `.project-header` | project.html | Project page header |
| `.data-list` | home.html | Data list grid |
| `.data-value` | home.html | Data list value |
| `.snapshot` | home.html | JSON snapshot display |
| `.status-pill` | system.html | Status pill variant |
| `.log-panel` | system.html | Log panel container |
| `.network-card` | system.html | Network status card |

> **Note:** The following classes are standard components defined in `components.css` with legacy aliases for backward compatibility. They should not be considered page-specific:
> - `.svc-state-*` — Service state colors
> - `.svc-desc-*` — Service description wrappers
> - `.hint` / `.c-hint` — Hint text styling
> - `.note` / `.c-note` — Note text styling
> - `.kbd` / `.c-kbd` — Keyboard key styling
> - `.spinner` / `.c-spinner` — Loading spinner
> - `.status-msg` / `.c-status-msg` — Status message
> - `.thumb` / `.c-thumb` — Thumbnail container

## Migration Guide

When migrating a page to use the new modular CSS:

1. **Replace layout classes**: Change `.wrap` → `.layout-main`, `.row` → `.l-row`, etc.
2. **Update component classes**: Use `c-` prefixed versions (`.c-card`, `.c-btn`, `.c-pill`)
3. **Apply state modifiers**: Use `.is-*` pattern (`.is-ok`, `.is-warn`, `.is-err`)
4. **Use utility prefix**: Switch to `.u-*` utilities (`.u-muted`, `.u-gap-md`)
5. **Keep page-specific**: Leave unique page styles in `[page].css` (<150 lines)

### Example Migration

**Before:**
```html
<div class="wrap">
  <div class="card">
    <h3>Title</h3>
    <span class="pill ok">Active</span>
  </div>
</div>
```

**After:**
```html
<main class="layout-main">
  <article class="c-card">
    <h3 class="c-card__title">Title</h3>
    <span class="c-pill is-ok">Active</span>
  </article>
</main>
```

## Naming Conventions

- `l-*` — Layout primitives (l-row, l-grid, l-stack)
- `c-*` — Components (c-card, c-btn, c-pill)
- `u-*` — Utilities (u-muted, u-gap-md, u-mt-lg)
- `is-*` / `has-*` — State modifiers (is-ok, is-active, has-error)

## Related Files

- `../dashboard-common.css` — Main entry point with legacy fallbacks
- `../../layout-page.html` — HTML template for new pages
- `../../../docs_pl/styleguide.md` — Full style documentation
