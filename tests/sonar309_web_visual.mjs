// Local rendering evidence only: no application scripts, links, media sources or network.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
const root = new URL('../', import.meta.url);
const read = name => readFile(new URL(name, root), 'utf8');
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');

export async function styleFixture({ label, control, removePriority = false }) {
  const common = ['tokens', 'base', 'layout', 'components', 'utilities', 'menu', 'footer'];
  let css = (await Promise.all(common.map(name => read('web/assets/css/' + name + '.css')))).join('\n');
  css += '\n' + (await Promise.all(['classic', 'classic-plus', 'v2', 'v3'].map(name => read('web/assets/themes/' + name + '/theme.css')))).join('\n');
  css += '\n' + await read('web/assets/operator/operator.css');
  css += '\n' + (control ?? await read('web/assets/pages/control.css'));
  css += '\n' + await read('web/assets/pages/system.css');
  if (removePriority) css = css.replaceAll(/display:\s*none\s*!important/g, 'display: none');
  const probes = ['c-card', 'page-header', 'c-section'].map((surface, index) =>
    '<section class="' + surface + '" data-surface="' + surface + '"><h2>' + surface + '</h2>' +
    '<span class="version-branch" data-contrast="branch" id="branch-' + index + '">release-309</span> ' +
    '<span class="version-dirty" data-contrast="dirty" id="dirty-' + index + '">dirty</span>' +
    '<div class="edge-list"><span data-contrast="edge" id="edge-' + index + '">service → dependency</span></div></section>').join('\n');
  return '<!doctype html><html lang="en" data-dashboard-theme="classic"><head><meta charset="utf-8">' +
    '<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; style-src &apos;unsafe-inline&apos;; base-uri &apos;none&apos;; form-action &apos;none&apos;">' +
    '<title>' + escape(label) + '</title><style>' + css + '</style></head>' +
    '<body class="page page-control page-system"><main class="layout-main operator-shell">' +
    '<h1>' + escape(label) + '</h1><p>Standalone authored CSS; no application JavaScript or I/O.</p>' +
    '<section class="control-primary"><div class="cam-card c-card"><div class="media-frame">' +
    '<img id="camera-hidden" class="cam" hidden alt="Hidden camera">' +
    '<img id="camera-visible" class="cam" width="160" height="80" alt="Visible placeholder">' +
    '<canvas id="canvas-hidden" class="cam" hidden style="display:none"></canvas>' +
    '<canvas id="canvas-visible" class="cam" width="160" height="80"></canvas></div></div>' +
    '<div><output id="operator-output-hidden" aria-live="polite" hidden>Hidden output</output>' +
    '<output id="operator-output-visible" aria-live="polite">Visible output</output></div></section>' +
    '<section class="c-card" id="operator-admin-hidden" data-motion-admin hidden>Hidden administration</section>' +
    '<label class="motion-setting-field" id="operator-field-hidden" hidden>Hidden motion field<input type="number"></label>' +
    '<label class="operator-option engine-field" id="operator-label-hidden" hidden>Hidden option<select><option>inert</option></select></label>' +
    '<textarea id="operator-textarea-hidden" hidden>Hidden textarea</textarea>' +
    '<canvas class="operator-map" id="operator-map-hidden" hidden></canvas>' +
    '<button class="c-btn operator-stop" id="operator-stop-hidden" hidden>Hidden button; no handler</button>' +
    '<span class="motion-field-error" id="operator-error-hidden" hidden>Hidden error</span>' +
    '<div id="operator-inline-hidden" hidden style="display:flex">Inline display is still hidden</div>' +
    '<div id="utility-hidden" class="u-hidden" style="display:flex">Always hidden utility</div>' +
    '<div id="utility-mobile" class="u-hide-mobile" style="display:grid">Mobile hidden utility</div>' +
    '<div id="utility-desktop" class="u-hide-desktop" style="display:block">Desktop hidden utility</div>' +
    '<div id="utility-print" class="u-print-hidden" style="display:inline-flex">Print hidden utility</div>' +
    probes + '</main></body></html>';
}

export async function writeStyleFixtures(output, baseline) {
  await mkdir(output, { recursive: true });
  const variants = [
    ['before', { label: 'BEFORE: main 9a5af25', control: baseline.control }],
    ['after', { label: 'AFTER: camera presentation respects hidden' }],
    ['counterexample-before', { label: 'HYPOTHETICAL: before without priority (not production)', control: baseline.control, removePriority: true }],
    ['counterexample-after', { label: 'HYPOTHETICAL: after without priority (not production)', removePriority: true }],
  ];
  for (const [name, options] of variants) await writeFile(join(output, name + '.html'), await styleFixture(options));
  const instructions = {
    scope: 'Use only these standalone local files. Block all network, disable application scripts. No Rider/Venom/device URL or service.',
    themes: ['classic', 'classic-plus', 'v2', 'v3'],
    theme_switch: 'Set document.documentElement.dataset.dashboardTheme to each theme through browser automation; the fixture contains all original theme CSS.',
    viewports: [{ width: 1280, height: 1000 }, { width: 390, height: 844 }],
    media: ['screen', 'print'],
    variants: variants.map(([name]) => name + '.html'),
    checks: [
      'Before/after all IDs ending -hidden plus operator-inline-hidden have display:none, including camera, canvas, field, output, admin, textarea, map and STOP button.',
      'Visible camera/canvas remain display:block; visible output retains its original layout. Compare camera card geometry before/after.',
      'utility-hidden is none always; utility-mobile is none at width<=768; utility-desktop is none at width>=769; utility-print is none in print. Outside its range each utility keeps its authored inline display.',
      'Counterexample variants are deliberate negative controls, not proposed code: inline operator and utilities lose hiding if priority is removed. Desktop camera hidden is incorrectly block only in counterexample-before; the after visible-only selector fixes that conflict.',
      'Read actual computed color/backgroundColor and ancestor paints for the 9 data-contrast nodes per theme. Composite alpha over authored dark backgrounds; require text contrast>=4.5:1. Report measurements per branch/dirty/edge. Keep any screenshot/gradient assumptions explicit.',
    ],
    limits: 'These fixtures contain exact authored CSS flattened in original entry-point order plus system.css activated intentionally to test the reported legacy selectors. They are not the live operator page and do not test hardware, interaction, endpoint behavior or unsupported browsers.',
  };
  await writeFile(join(output, 'instructions.json'), JSON.stringify(instructions, null, 2) + '\n');
}
if (process.argv[2] === '--write-fixtures') {
  const baseline = JSON.parse(await readFile(process.argv[4], 'utf8'));
  await writeStyleFixtures(process.argv[3], baseline);
}
