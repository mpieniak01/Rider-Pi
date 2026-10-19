"""HTML/CSS source contracts; the release owner also checks actual Chrome rendering.

These checks use the repository's authored CSS blocks, not a browser layout engine.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATUS_IDS = {
    'calibration': ['manual-settings-status', 'operator-message', 'motion-profile-status', 'manual-settings-result'],
    'chat': ['operator-message'],
    'control': [
        'motion-profile-status',
        'manual-settings-status',
        'operator-message',
        'control-camera-status',
        'manual-settings-result',
        'manual-settings-feedback',
    ],
    'devices': ['operator-message', 'camera-power-state'],
    'face-studio': ['studio-status', 'runtime-status'],
    'navigation': ['operator-message'],
    'system': ['operator-message'],
    'view': [
        'operator-message',
        'history-status',
        'camera-power-state',
        'camera-proc-state',
        'camera-obst-state',
        'camera-tracker-state',
    ],
}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.nodes = []
        self.by_id = {}
        self.feed(source)
        assert not self.stack

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs), 'ancestors': self.stack.copy(), 'text': ''}
        self.nodes.append(node)
        if 'id' in node['attrs']:
            assert node['attrs']['id'] not in self.by_id
            self.by_id[node['attrs']['id']] = node
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        assert self.stack, tag
        assert self.stack[-1]['tag'] == tag, (tag, self.stack[-1]['tag'])
        self.stack.pop()

    def handle_data(self, data):
        for node in self.stack:
            node['text'] += data


def read(path):
    return (ROOT / path).read_text()


def block_end(source, opening):
    closing = opening + 1
    depth = 1
    while depth:
        assert closing < len(source)
        depth += (source[closing] == '{') - (source[closing] == '}')
        closing += 1
    return closing


def declarations(body):
    result = {}
    for declaration in body.split(';'):
        if ':' in declaration:
            key, value = declaration.split(':', 1)
            result[key.strip()] = value.strip()
    return result


def css_blocks(source, context=()):
    """Read balanced authored blocks while retaining their at-rule context."""
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    offset = 0
    while offset < len(source):
        opening = source.find('{', offset)
        if opening < 0:
            return
        header = source[offset:opening].strip()
        closing = block_end(source, opening)
        body = source[opening + 1 : closing - 1]
        if header.startswith('@'):
            yield from css_blocks(body, context + (header,))
        else:
            properties = declarations(body)
            for selector in header.split(','):
                yield context, selector.strip(), properties
        offset = closing


def rule(path, selector, context=()):
    matches = [body for scope, candidate, body in css_blocks(read(path)) if scope == context and candidate == selector]
    assert len(matches) == 1, (path, selector, context, len(matches))
    return matches[0]


@pytest.mark.parametrize('page,ids', STATUS_IDS.items())
def test_status_outputs_keep_live_atomic_announcements_and_no_form_reset_association(page, ids):
    document = Document(read('web/' + page + '.html'))
    for identity in ids:
        node = document.by_id[identity]
        assert node['tag'] == 'output'
        assert node['attrs']['aria-live'] == 'polite'
        assert node['attrs']['aria-atomic'] == 'true'
        assert 'role' not in node['attrs']
        assert 'form' not in node['attrs']
        assert 'name' not in node['attrs']
        assert 'tabindex' not in node['attrs']
        assert not [parent for parent in node['ancestors'] if parent['tag'] == 'form']
    assert not [node for node in document.nodes if node['attrs'].get('role') == 'status']


def test_language_group_is_native_named_and_keeps_non_submit_buttons():
    document = Document(read('web/dashboard_menu_template.html'))
    groups = [node for node in document.nodes if node['attrs'].get('class') == 'lang-switch']
    assert len(groups) == 1
    group = groups[0]
    assert group['tag'] == 'fieldset'
    assert group['attrs']['aria-label'] == 'Language switch'
    buttons = [node for node in document.nodes if group in node['ancestors'] and node['tag'] == 'button']
    assert [node['attrs']['data-lang'] for node in buttons] == ['pl', 'en']
    assert all(node['attrs']['type'] == 'button' for node in buttons)
    reset = rule('web/assets/css/menu.css', '.lang-switch')
    assert reset['display'] == 'flex'
    assert reset['border'] == '0'
    assert reset['padding'] == '0'
    assert reset['min-width'] == '0'
    assert reset['margin'] == '0 0 0 auto'


@pytest.mark.parametrize(
    'path,targets',
    [
        ('web/assets/css/menu.css', {'.dashboard-menu .brand', '.dashboard-menu a'}),
        ('web/assets/pages/view.css', {'.page-view .view-row', '.page-view .c-kv'}),
        (
            'web/assets/pages/system.css',
            {
                '.page-system .services-grid',
                '.page-system .service-node',
                '.page-system .service-node:hover',
                '.page-system .service-node__head',
                '.page-system .service-node__title',
            },
        ),
    ],
)
def test_target_selector_merge_preserves_distinct_responsive_contexts(path, targets):
    seen = set()
    for context, selector, _ in css_blocks(read(path)):
        if selector not in targets:
            continue
        key = context, selector
        assert key not in seen, key
        seen.add(key)
    assert targets <= {selector for context, selector in seen if not context}


def test_viewport_grid_and_service_state_policies_survive_rule_consolidation():
    view = 'web/assets/pages/view.css'
    assert rule(view, '.page-view .view-row')['grid-template-columns'] == 'repeat(4, minmax(0, 1fr))'
    assert (
        rule(view, '.page-view .view-row', ('@media (max-width: 1050px)',))['grid-template-columns']
        == 'repeat(2, minmax(0, 1fr))'
    )
    assert (
        rule(view, '.page-view .view-row', ('@media (max-width: 600px)',))['grid-template-columns'] == 'minmax(0, 1fr)'
    )
    system = 'web/assets/pages/system.css'
    node = rule(system, '.page-system .service-node')
    assert node['cursor'] == 'default'
    assert node['min-width'] == '0'
    assert node['height'] == 'auto'
    assert node['overflow-wrap'] == 'anywhere'
    assert rule(system, '.page-system .service-node:hover')['transform'] == 'none'
    assert (
        rule(system, '.page-system .service-node.is-active:hover')['box-shadow'] == '0 4px 12px rgba(34, 197, 94, 0.25)'
    )
    assert (
        rule(system, '.page-system .service-node.is-failed:hover')['box-shadow'] == '0 4px 12px rgba(239, 68, 68, 0.25)'
    )
    assert rule(system, '.page-system .service-node__head')['align-items'] == 'flex-start'
    assert rule(system, '.page-system .service-node__head')['flex-wrap'] == 'wrap'
    assert rule(system, '.page-system .service-node__title')['min-width'] == '0'
    menu = 'web/assets/css/menu.css'
    assert rule(menu, '.dashboard-menu .brand')['margin-right'] == '0'
    assert rule(menu, '.dashboard-menu a')['white-space'] == 'nowrap'
    assert rule(menu, '.dashboard-menu ul', ('@media (min-width: 1051px)',))['flex-wrap'] == 'nowrap'
    assert rule(menu, '.dashboard-menu ul', ('@media (max-width: 1050px)',))['display'] == 'none'
    assert rule(menu, '.dashboard-menu.menu-open ul', ('@media (max-width: 1050px)',))['display'] == 'flex'


@pytest.mark.parametrize(
    'path,selector',
    [
        ('web/assets/css/components.css', '.log-entry'),
        ('web/assets/css/utilities.css', '.u-break-word'),
        ('web/assets/pages/chat-pc.css', '.page-chat-pc #provider-hint'),
        ('web/assets/pages/chat.css', '.page-chat #provider-hint'),
        ('web/assets/pages/chat.css', '.page-chat .msg'),
    ],
)
def test_long_unbroken_words_retain_wrap_opportunities_and_normal_word_boundaries(path, selector):
    properties = rule(path, selector)
    assert properties['word-break'] == 'normal'
    assert properties['overflow-wrap'] == 'anywhere'
    assert not re.search(r'word-break\s*:\s*break-word', read(path))


def test_status_geometry_retains_spacing_empty_message_rules_and_numeric_output_layout():
    path = 'web/assets/css/components.css'
    status = rule(path, 'output:where([aria-live])')
    assert status['display'] == 'block'
    assert status['margin'] == '0 0 var(--space-md)'
    assert status['line-height'] == 'var(--line-height-normal)'
    assert rule(path, '.page-control .control-primary output[aria-live]')['display'] == 'block'
    assert rule(path, '.page-calibration .control-primary output[aria-live]')['margin'] == '.5rem 0'
    assert rule(path, '.page-calibration .calibration-settings > output[aria-live]')['margin'] == '.4rem 0'
    assert rule('web/assets/pages/view.css', '.page-view .operator-message:empty')['display'] == 'none'
    assert (
        rule('web/assets/operator/calibration.css', '.page-calibration #manual-settings-result:empty')['display']
        == 'none'
    )
    assert rule('web/assets/pages/control.css', '.page-control .control-primary output')['display'] == 'inline-block'
    assert rule('web/assets/pages/view.css', '.page-view .c-hint')['margin-bottom'] == 'var(--space-xl)'


def test_google_hidden_wins_existing_card_and_grid_display_rules_without_important():
    path = 'web/assets/pages/google-home.css'
    properties = rule(path, '.page-google .hidden')
    assert properties['display'] == 'none'
    assert '!important' not in read(path)
    document = Document(read('web/google_home.html'))
    hidden = [node for node in document.nodes if 'hidden' in node['attrs'].get('class', '').split()]
    assert [node['attrs'].get('id') for node in hidden] == ['authSection', 'devicesSection', 'statusMsg']
    assert all('style' not in node['attrs'] for node in hidden)
    assert all(node['attrs'].get('class', '').split()[0] in {'c-card', 'c-status-msg'} for node in hidden)
    for theme in ['classic', 'classic-plus', 'v2', 'v3']:
        for _, selector, body in css_blocks(read('web/assets/themes/' + theme + '/theme.css')):
            if selector.endswith('.c-card'):
                assert 'display' not in body


def rgba(value):
    if value.startswith('#'):
        return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5)) + (1.0,)
    assert value.startswith('rgba('), value
    return tuple(float(part) for part in re.findall(r'[\d.]+', value))


def composite(front, back):
    return tuple(front[index] * front[3] + back[index] * (1 - front[3]) for index in range(3)) + (1.0,)


def luminance(color):
    values = [component / 255 for component in color[:3]]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(component * weight for component, weight in zip(linear, [0.2126, 0.7152, 0.0722]))


def contrast(foreground, background):
    low, high = sorted([luminance(foreground), luminance(background)])
    return (high + 0.05) / (low + 0.05)


def resolved_theme(theme):
    tokens = rule('web/assets/css/tokens.css', ':root')
    source = read('web/assets/themes/' + theme + '/theme.css')
    for _, selector, properties in css_blocks(source):
        if selector.startswith(':root['):
            tokens.update({key: value for key, value in properties.items() if key.startswith('--')})
    for _ in range(len(tokens)):
        updated = source
        for key, value in tokens.items():
            updated = updated.replace('var(' + key + ')', value)
        if source == updated:
            break
        source = updated
    return tokens, source


def surface_colors(theme):
    tokens, source = resolved_theme(theme)
    primary = rgba(tokens['--color-bg-primary'])
    surfaces = [primary, rgba(tokens['--color-bg-secondary']), rgba(tokens['--color-bg-elevated'])]
    # Composite each authored gradient tint at its maximum over the layout base.
    # Checking all zero/peak tint combinations bounds the actual interpolated backdrop.
    main = next(body for _, selector, body in css_blocks(source) if selector.endswith('.layout-main'))
    backdrops = [primary]
    for tint in reversed(re.findall(r'rgba\([^)]*\)', main['background'])):
        backdrops += [composite(rgba(tint), back) for back in backdrops]
    surfaces += backdrops
    for _, selector, body in css_blocks(source):
        if not selector.endswith(('.c-card', '.page-header', '.c-section')):
            continue
        background = body.get('background', '')
        if background.startswith('var('):
            continue  # Card token surface colors are already included above.
        for paint in re.findall(r'rgba\([^)]*\)|#[\da-fA-F]{6}', background):
            surfaces += [composite(rgba(paint), back) for back in backdrops]
    return surfaces


@pytest.mark.parametrize('theme', ['classic', 'classic-plus', 'v2', 'v3'])
@pytest.mark.parametrize(
    'selector', ['.page-system .version-branch', '.page-system .version-dirty', '.page-system .edge-list span']
)
def test_flagged_text_contrast_on_real_dark_theme_surfaces_includes_alpha_and_gradients(theme, selector):
    properties = rule('web/assets/pages/system.css', selector)
    foreground = rgba(properties['color'])
    background = rgba(properties['background'])
    ratios = [contrast(foreground, composite(background, surface)) for surface in surface_colors(theme)]
    assert min(ratios) >= 4.5, (theme, selector, min(ratios))


def test_contrast_reference_pairs_and_alpha_composition_are_not_assumed_accessible():
    assert contrast(rgba('#ffffff'), rgba('#000000')) == 21
    assert contrast(rgba('#ffffff'), rgba('#ffffff')) == 1
    assert contrast(rgba('#777777'), rgba('#ffffff')) < 4.5
    assert composite(rgba('rgba(200, 100, 0, 0.25)'), rgba('#000000')) == (50, 25, 0, 1)
