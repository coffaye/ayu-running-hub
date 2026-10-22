import json
import pytest
from ayu_report_engine.themes import THEMES, normalize_theme, theme_instructions, validate_theme_html
from ayu_report_engine.native_agent import build_model_request, load_native_material


def themed_html(theme):
    values=THEMES[theme]
    css=':root{'+''.join(f'--ayu-{key}:{value};' for key,value in values.items())+'}'
    return '<!doctype html><html><head><style>'+css+'</style></head><body data-ayu-theme="'+theme+'"><script>const AYU_THEME_TOKENS='+json.dumps(values)+';</script></body></html>'


@pytest.mark.parametrize('theme',list(THEMES))
def test_theme_contract_binds_html_and_canvas(theme):
    assert validate_theme_html(themed_html(theme),theme)['themeValidation'] is True
    assert theme in theme_instructions(theme)
    request=build_model_request(load_native_material(),{'reportTheme':theme})
    assert f'Selected presentation theme: {theme}.' in request['instructions']
    assert 'ONE theme' in request['instructions']


def test_theme_gate_rejects_wrong_theme_and_stale_canvas_palette():
    with pytest.raises(ValueError):validate_theme_html(themed_html('blue'),'burgundy')
    html=themed_html('burgundy').replace('"accent": "#A61D4B"','"accent": "#56FFA3"')
    with pytest.raises(ValueError):validate_theme_html(html,'burgundy')
    with pytest.raises(ValueError):normalize_theme('all')
    assert normalize_theme()=='black-green'


def test_theme_gate_rejects_demonstrated_palette_helper_collision():
    html=themed_html('burgundy').replace('</script>','var T=AYU_THEME_TOKENS;function T(s,x,y){return y+20;}</script>')
    with pytest.raises(ValueError,match='conflicts'):validate_theme_html(html,'burgundy')
