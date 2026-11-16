import numpy as np
import pytest
from PIL import Image

from sonhangul.errors import SonError
from sonhangul.export import normal_map, save_pdf, save_texture_set
from sonhangul.ink import get_pen
from sonhangul.page import PageOptions, letter, mm_to_px, page_pixels, render_page
from sonhangul.paper import PAPERS
from sonhangul.render import HandStyle

BODY = "한 해 동안 고마웠어요. 내년에도 잘 부탁드려요."


def test_page_pixels():
    assert page_pixels("a6", 300) == (1240, 1748)
    assert page_pixels("A6", 300, landscape=True) == (1748, 1240)
    assert mm_to_px(25.4, 300) == 300
    with pytest.raises(SonError):
        page_pixels("letter", 300)


@pytest.mark.parametrize("paper", sorted(PAPERS))
def test_every_paper_renders(font, paper):
    page = render_page(BODY, HandStyle(size=36, seed=1), get_pen("gel"), PageOptions(width=500, paper=paper))
    assert page.image.width == 500
    if paper == "transparent":
        assert page.image.mode == "RGBA"
        assert page.image.getchannel("A").getextrema() [0] == 0
    else:
        assert page.image.mode == "RGB"
        # 잉크가 종이보다 어두운 곳이 있어야 한다
        assert np.asarray(page.image.convert("L")).min() < 120


def test_blank_paper_is_pure_white_where_no_ink(font):
    page = render_page(BODY, HandStyle(size=36, seed=1), get_pen("gel"), PageOptions(width=500, paper="blank"))
    assert page.image.getpixel((2, 2)) == (255, 255, 255)


def test_fixed_card_shrinks_text_to_fit(font):
    long_body = BODY * 12
    opts = PageOptions(width=500, height=400, paper="blank")
    page = render_page(long_body, HandStyle(size=40, seed=1), get_pen("gel"), opts)
    assert page.shrunk and page.size < 40
    assert page.image.size == (500, 400)
    ys = np.concatenate([c[:, 1] for g in page.layout.glyphs for c in g.contours])
    assert ys.max() < 400


def test_no_fit_keeps_size(font):
    opts = PageOptions(width=500, height=300, paper="blank", fit=False)
    page = render_page(BODY * 12, HandStyle(size=40, seed=1), get_pen("gel"), opts)
    assert page.size == 40 and not page.shrunk


def test_center_valign_moves_short_text_down(font):
    def top_of(valign):
        opts = PageOptions(width=600, height=800, paper="blank", valign=valign)
        page = render_page("짧은 글", HandStyle(size=40, seed=1), get_pen("gel"), opts)
        return np.nonzero(page.alpha.max(axis=1) > 0.1)[0][0]

    assert top_of("center") > top_of("top") + 150


def test_lined_paper_text_sits_on_rules(font):
    opts = PageOptions(width=700, height=600, paper="lined")
    page = render_page(BODY * 3, HandStyle(size=36, seed=1), get_pen("gel"), opts)
    assert len(page.layout.baselines) >= 2
    gaps = np.diff(page.layout.baselines)
    pitch = 36 * 1.6
    # 줄 간격의 배수(지터 조금)로 떨어져야 한다
    assert np.all(np.abs(gaps / pitch - np.round(gaps / pitch)) < 0.15)


def test_letter_structure():
    paras = letter("본문", to="민수 님께", sender="서연 드림", date="11월 16일")
    assert [p.align for p in paras] == ["left", "left", "right", "right"]
    assert letter("본문")[0].space_before == 0


def test_pdf_has_physical_page_size(font, tmp_path):
    w, h = page_pixels("a6", 150)
    opts = PageOptions(width=w, height=h, paper="blank", dpi=150, valign="center")
    pages = [render_page(BODY, HandStyle(size=30, seed=s), get_pen("gel"), opts) for s in (1, 2)]
    path = save_pdf(pages, tmp_path / "cards.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 2 or data.count(b"/MediaBox") >= 2
    # A6 = 105 x 148 mm = 297.6 x 419.5 pt
    import re

    box = re.search(rb"/MediaBox \[ ?0 0 ([\d.]+) ([\d.]+) ?\]", data)
    assert box, "MediaBox 를 찾지 못함"
    assert abs(float(box.group(1)) - 297.6) < 1.5 and abs(float(box.group(2)) - 419.5) < 1.5


def test_texture_set(font, tmp_path):
    page = render_page(BODY, HandStyle(size=36, seed=1), get_pen("pencil"), PageOptions(width=400, paper="aged"))
    paths = save_texture_set(page, tmp_path / "note.png")
    assert [p.name for p in paths] == ["note.png", "note_ink.png", "note_normal.png", "note_roughness.png"]
    ink = Image.open(paths[1])
    assert ink.mode == "RGBA" and ink.size == page.image.size
    normal = np.asarray(normal_map(page), dtype=np.float32)
    # 잉크가 없는 평평한 곳은 (128, 128, 255)
    assert np.allclose(normal[1, 1], (128, 128, 255), atol=2)
    assert normal[..., 2].min() < 250


def test_overflow_is_reported_when_text_cannot_fit(font):
    opts = PageOptions(width=500, height=300, paper="blank", fit=False)
    page = render_page(BODY * 12, HandStyle(size=40, seed=1), get_pen("gel"), opts)
    assert page.layout.overflow
    ok = render_page("짧아요", HandStyle(size=40, seed=1), get_pen("gel"), PageOptions(width=500, height=300, paper="blank"))
    assert not ok.layout.overflow
