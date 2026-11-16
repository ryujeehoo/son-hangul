import numpy as np
import pytest

from sonhangul.errors import SonError
from sonhangul.fonts import FontChain, load_font
from sonhangul.ink import PENS, get_pen, parse_color
from sonhangul.render import HandStyle, Paragraph, layout_text, render_text


def _ink(text, **kw):
    style = HandStyle(size=40, seed=kw.pop("seed", 1), **kw)
    return render_text(text, style, get_pen("gel"), width=700)


def test_same_seed_same_image(font):
    a, b = _ink("손으로 쓴 것처럼"), _ink("손으로 쓴 것처럼")
    assert np.array_equal(a.alpha, b.alpha)


def test_different_seed_different_image(font):
    a, b = _ink("손으로 쓴 것처럼", seed=1), _ink("손으로 쓴 것처럼", seed=2)
    assert a.alpha.shape != b.alpha.shape or not np.array_equal(a.alpha, b.alpha)


def test_same_letter_is_drawn_differently_each_time(font):
    """같은 글자를 여러 번 쓰면 윤곽선이 매번 달라야 한다(폰트 티가 나지 않게)."""
    layout = layout_text([Paragraph("가가가가")], HandStyle(size=60, seed=3), width=900)
    shapes = []
    for g in layout.glyphs:
        pts = np.concatenate(g.contours)
        shapes.append(pts - pts.mean(axis=0))  # 위치 차이는 빼고 모양만 비교
    assert len(shapes) == 4
    for i in range(4):
        for j in range(i + 1, 4):
            assert np.abs(shapes[i] - shapes[j]).max() > 0.3, "두 '가' 가 픽셀 단위로 거의 같다"


def test_messiness_zero_repeats_the_font_shape(font):
    layout = layout_text([Paragraph("가가")], HandStyle(size=60, seed=3, messiness=0), width=900)
    a, b = (np.concatenate(g.contours) for g in layout.glyphs)
    assert np.allclose(a - a.mean(axis=0), b - b.mean(axis=0), atol=1e-6)


@pytest.mark.parametrize("text", ["값없닭읽앉 삶훑", "Hello, World! 123", "괜찮아요? 네~ (정말) \"따옴표\" 50%"])
def test_mixed_characters_render_without_missing(font, text):
    ink = _ink(text)
    assert not ink.layout.missing
    assert ink.alpha.max() > 0.5
    drawn = [g for g in ink.layout.glyphs if g.contours]
    assert len(drawn) == len(text.replace(" ", ""))


def test_unknown_character_is_reported_not_crashed(font):
    ink = _ink("가\U0001F600나")
    assert "\U0001F600" in ink.layout.missing
    assert len(ink.layout.glyphs) == 2


def test_long_text_wraps_inside_width(font):
    layout = layout_text(
        [Paragraph("가나다라 " * 30)], HandStyle(size=40, seed=1), width=600, margin=(30, 30, 30, 30)
    )
    assert len(layout.baselines) > 3
    xs = np.concatenate([c[:, 0] for g in layout.glyphs for c in g.contours])
    assert xs.min() > 0 and xs.max() < 600


def test_very_long_word_is_split(font):
    layout = layout_text([Paragraph("가" * 80)], HandStyle(size=40, seed=1), width=500, margin=(20, 20, 20, 20))
    assert len(layout.baselines) > 2


def test_right_align_ends_near_right_margin(font):
    layout = layout_text(
        [Paragraph("드림", align="right")], HandStyle(size=40, seed=1), width=800, margin=(40, 40, 40, 40)
    )
    xs = np.concatenate([c[:, 0] for g in layout.glyphs for c in g.contours])
    assert 650 < xs.max() < 800


def test_fallback_font_fills_glyphs_missing_from_gaegu():
    try:
        chain = FontChain("gaegu")
        load_font("nanum-pen")
    except SonError as exc:
        pytest.skip(str(exc))
    assert not chain.primary.has("힣")
    assert chain.lookup("힣") is not None
    assert not chain.missing


def test_every_pen_produces_ink(font):
    for key in PENS:
        ink = render_text("펜마다 달라요", HandStyle(size=40, seed=1), get_pen(key), width=600)
        assert 0.3 < ink.alpha.max() <= 1.0, key
        assert ink.alpha.min() >= 0.0


def test_parse_color():
    assert parse_color("#102030") == (16, 32, 48)
    assert parse_color("1, 2, 3") == (1, 2, 3)
    with pytest.raises(SonError):
        parse_color("빨강")
    with pytest.raises(SonError):
        get_pen("crayon")
