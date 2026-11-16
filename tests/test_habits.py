import numpy as np
import pytest

from sonhangul import cli
from sonhangul.errors import SonError
from sonhangul.fonts import load_font
from sonhangul.habits import Habits, apply_habits, get_habits, random_habits, segments_for
from sonhangul.jamo import decompose, layout_of, segment
from sonhangul.render import HandStyle, Paragraph, layout_text


def _box(contours, idx):
    pts = np.concatenate([contours[i] for i in idx])
    return pts.min(axis=0), pts.max(axis=0)


def test_decompose():
    assert decompose("한") == ("ㅎ", "ㅏ", "ㄴ")
    assert decompose("과") == ("ㄱ", "ㅘ", "")
    assert decompose("A") is None and decompose("ㄱ") is None
    assert [layout_of(v) for v in "ㅏㅗㅘ"] == ["v", "h", "m"]


def test_segment_puts_jamo_where_they_belong(font):
    f = load_font(font)
    ga = f.outline("가")
    s = segment("가", ga.contours)
    assert s and s.cho and s.jung and not s.jong
    assert _box(ga.contours, s.cho)[1][0] < _box(ga.contours, s.jung)[1][0], "초성이 모음보다 왼쪽"

    han = f.outline("한")
    s = segment("한", han.contours)
    assert s and s.jong
    assert _box(han.contours, s.jong)[1][1] < _box(han.contours, s.cho)[1][1], "받침이 초성보다 아래"
    assert sorted(s.cho + s.jung + s.jong) == list(range(len(han.contours))), "모든 윤곽선이 한 자모에 속함"

    go = f.outline("고")
    s = segment("고", go.contours)
    assert s and _box(go.contours, s.cho)[0][1] > _box(go.contours, s.jung)[0][1], "초성이 모음보다 위"


def test_segment_refuses_non_hangul_and_merged_glyphs(font):
    f = load_font(font)
    assert segment("A", f.outline("A").contours) is None
    one_blob = [np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)]
    assert segment("가", one_blob) is None, "덩어리가 하나면 나눌 수 없다"


def _cho_height(font, ch, habits):
    g = load_font(font).outline(ch)
    seg = segments_for(ch, g)
    out, _ = apply_habits(ch, g.contours, g.advance, habits, seg, np.random.default_rng(0), 0.0)
    lo, hi = _box(out, seg.cho)
    return hi[1] - lo[1]


def test_big_cho_enlarges_only_the_initial_consonant(font):
    g = load_font(font).outline("가")
    seg = segments_for("가", g)
    plain, adv0 = apply_habits("가", g.contours, g.advance, Habits(), seg, np.random.default_rng(0), 0.0)
    big, adv1 = apply_habits("가", g.contours, g.advance, get_habits("big-cho", vowel=1.0), seg, np.random.default_rng(0), 0.0)
    h0 = np.ptp(np.concatenate([plain[i] for i in seg.cho])[:, 1])
    h1 = np.ptp(np.concatenate([big[i] for i in seg.cho])[:, 1])
    assert h1 / h0 == pytest.approx(1.22, abs=0.01)
    v0 = np.ptp(np.concatenate([plain[i] for i in seg.jung])[:, 1])
    v1 = np.ptp(np.concatenate([big[i] for i in seg.jung])[:, 1])
    assert v1 == pytest.approx(v0), "모음은 그대로"
    assert adv1 >= adv0, "커진 만큼 자리를 더 차지한다"


def test_ieung_habit_touches_only_ieung(font):
    small = get_habits("small-ieung")
    assert _cho_height(font, "아", small) / _cho_height(font, "아", Habits()) == pytest.approx(0.62, abs=0.01)
    assert _cho_height(font, "가", small) == pytest.approx(_cho_height(font, "가", Habits()))


def test_small_vowel_shortens_vertical_vowels(font):
    g = load_font(font).outline("가")
    seg = segments_for("가", g)
    out, _ = apply_habits("가", g.contours, g.advance, get_habits("small-vowel"), seg, np.random.default_rng(0), 0.0)
    before = np.ptp(np.concatenate([g.contours[i] for i in seg.jung])[:, 1])
    after = np.ptp(np.concatenate([out[i] for i in seg.jung])[:, 1])
    assert after / before == pytest.approx(0.72, abs=0.01)


def test_merged_glyph_still_gets_the_habit_smoothly(font):
    """획이 붙어 못 나눈 글자도 버릇이 빠지면 안 된다(그 글자만 평범해 보인다)."""
    f = load_font(font)
    merged = next(ch for ch in "노도로모보그드르므" if segment(ch, f.outline(ch).contours) is None)
    g = f.outline(merged)
    out, _ = apply_habits(merged, g.contours, g.advance, get_habits("big-cho"), None, np.random.default_rng(0), 0.0)
    moved = max(float(np.abs(a - b).max()) for a, b in zip(out, g.contours))
    assert 0.01 < moved < 0.3, "조금은 바뀌되 글자가 망가질 만큼은 아니다"
    assert all(len(a) == len(b) for a, b in zip(out, g.contours))


def test_habit_is_consistent_across_the_text(font):
    """버릇은 같은 글자에 매번 똑같이 나타난다(흐트러짐 0 일 때 완전히 같음)."""
    style = HandStyle(size=60, seed=1, messiness=0, wobble=0, habits=get_habits("big-cho,small-vowel"))
    layout = layout_text([Paragraph("가가가")], style, width=900)
    shapes = [np.concatenate(g.contours) for g in layout.glyphs]
    shapes = [s - s.mean(axis=0) for s in shapes]
    assert np.allclose(shapes[0], shapes[1], atol=1e-6) and np.allclose(shapes[1], shapes[2], atol=1e-6)


def test_non_hangul_only_gets_width_and_spacing(font):
    g = load_font(font).outline("A")
    out, adv = apply_habits("A", g.contours, g.advance, get_habits("big-cho,narrow"), None, np.random.default_rng(0), 0.05)
    assert np.allclose(out[0], g.contours[0] * (0.86, 1.0))
    assert adv == pytest.approx(g.advance * 0.86)


def test_random_habits_are_one_person_per_seed():
    assert random_habits(5) == random_habits(5)
    assert random_habits(5) != random_habits(6)
    h = get_habits("random", seed=5, cho=1.5)
    assert h.cho == 1.5 and h.jong == random_habits(5).jong


def test_get_habits_validates():
    assert get_habits(None) == Habits() and Habits().plain
    assert not get_habits("big-cho").plain
    combo = get_habits("big-cho, small-ieung")
    assert combo.cho == 1.22 and combo.ieung == 0.62
    with pytest.raises(SonError, match="모르는 버릇"):
        get_habits("pretty")
    with pytest.raises(SonError, match="0.4 ~ 2.0"):
        get_habits("none", cho=5)


def _vertical_spread(style, text="가" * 24):
    """같은 글자를 한 줄에 늘어놓았을 때 글자 밑이 얼마나 들쭉날쭉한지(글씨 크기 대비)."""
    layout = layout_text([Paragraph(text)], style, width=4000)
    assert len(layout.baselines) == 1
    bottoms = np.array([max(c[:, 1].max() for c in g.contours) for g in layout.glyphs])
    xs = np.array([np.concatenate(g.contours)[:, 0].mean() for g in layout.glyphs])
    resid = bottoms - np.polyval(np.polyfit(xs, bottoms, 1), xs)
    slope = np.polyfit(xs, bottoms, 1)[0]
    return float(resid.std() / style.size), abs(float(slope))


def test_lines_are_straight_by_default(font):
    spreads, slopes = zip(*[_vertical_spread(HandStyle(size=60, seed=s)) for s in range(8)])
    assert np.mean(spreads) < 0.03, "글자 밑이 글씨 크기의 3% 안에서 고르다"
    assert max(slopes) < 0.012, "줄 기울기는 0.7도 안쪽"


def test_wobble_zero_is_ruler_straight_and_wobble_scales(font):
    flat, slope = _vertical_spread(HandStyle(size=60, seed=1, messiness=0, wobble=0))
    assert flat < 1e-6 and slope < 1e-9
    calm = np.mean([_vertical_spread(HandStyle(size=60, seed=s, messiness=0, wobble=1))[0] for s in range(6)])
    wild = np.mean([_vertical_spread(HandStyle(size=60, seed=s, messiness=0, wobble=4))[0] for s in range(6)])
    assert wild > calm * 2.5


def test_glyph_size_stays_even(font):
    """같은 글자를 30번 써도 높이 편차가 글씨 크기의 4% 를 넘지 않는다(이전 방식은 4.4%)."""
    spreads = []
    for seed in range(10):
        layout = layout_text([Paragraph("가" * 30)], HandStyle(size=60, seed=seed, wobble=0), width=5000)
        heights = np.array([np.ptp(np.concatenate(g.contours)[:, 1]) for g in layout.glyphs])
        spreads.append(heights.std())
    assert 0.005 < np.mean(spreads) / 60 < 0.03, "조금은 다르되 들쭉날쭉하지는 않다"


def test_cli_habit_options(font, tmp_path, capsys):
    out = tmp_path / "h.png"
    assert cli.main(["render", "안녕하세요", "--habit", "big-cho,small-vowel", "--ieung", "0.7", "--wobble", "0",
                     "--seed", "1", "--width", "500", "-o", str(out)]) == 0
    assert out.is_file()
    assert cli.main(["render", "안녕", "--habit", "pretty", "-o", str(out)]) == 1
    assert "모르는 버릇" in capsys.readouterr().err
    assert cli.main(["list"]) == 0
    assert "big-cho" in capsys.readouterr().out
