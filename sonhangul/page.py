"""한 장 만들기: 글 배치 → 잉크 → 종이 합성. 크기 단위 변환과 자동 맞춤을 맡는다."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from PIL import Image

from .errors import SonError
from .ink import Pen
from .paper import DEFAULT_PAPER, composite, get_paper, make_paper
from .render import HandStyle, Layout, Paragraph, layout_text, render_ink

# 인쇄 규격 (가로, 세로) mm
PAGE_SIZES_MM: dict[str, tuple[float, float]] = {
    "a4": (210, 297),
    "a5": (148, 210),
    "a6": (105, 148),
    "b6": (125, 176),
    "postcard": (100, 148),
    "square": (130, 130),
}


def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm / 25.4 * dpi))


def page_pixels(name: str, dpi: int, landscape: bool = False) -> tuple[int, int]:
    key = name.lower()
    if key not in PAGE_SIZES_MM:
        raise SonError(f"모르는 용지입니다: {name}\n쓸 수 있는 용지: {', '.join(PAGE_SIZES_MM)}")
    w, h = PAGE_SIZES_MM[key]
    if landscape:
        w, h = h, w
    return mm_to_px(w, dpi), mm_to_px(h, dpi)


@dataclass
class PageOptions:
    width: int
    height: int | None = None  # None 이면 글 길이에 맞춘다
    margin: tuple[float, float, float, float] | None = None  # px (위, 오른쪽, 아래, 왼쪽)
    paper: str = DEFAULT_PAPER
    valign: str = "top"  # top | center (높이가 정해진 카드에서만 의미가 있다)
    fit: bool = True  # 글이 넘치면 글씨를 줄여서 맞춘다
    ss: int = 3  # 글자를 몇 배로 크게 그렸다 줄일지(윤곽 품질)
    dpi: int = 300


@dataclass
class Page:
    image: Image.Image  # 종이까지 합친 결과(RGB) 또는 투명 배경(RGBA)
    alpha: np.ndarray  # 잉크만(0..1)
    color: tuple[int, int, int]
    layout: Layout
    size: float  # 실제로 쓴 글씨 크기
    dpi: int
    shrunk: bool = False  # 넘쳐서 글씨를 줄였는지


def letter(
    body: str, *, to: str | None = None, sender: str | None = None, date: str | None = None
) -> list[Paragraph]:
    """편지 꼴 문단: 받는 사람 / 본문 / 날짜와 보내는 사람(오른쪽)."""
    paragraphs: list[Paragraph] = []
    if to:
        paragraphs.append(Paragraph(to.strip()))
    paragraphs.append(Paragraph(body.strip(), space_before=0.6 if to else 0.0))
    if date:
        paragraphs.append(Paragraph(date.strip(), align="right", space_before=0.6))
    if sender:
        paragraphs.append(Paragraph(sender.strip(), align="right", space_before=0.0 if date else 0.6))
    return paragraphs


def render_page(
    text: str | list[Paragraph], style: HandStyle, pen: Pen, options: PageOptions
) -> Page:
    paragraphs = [Paragraph(text)] if isinstance(text, str) else text
    info = get_paper(options.paper)
    if options.valign not in ("top", "center"):
        raise SonError(f"세로 맞춤은 top 또는 center 입니다: {options.valign}")
    layout_seed, ink_seed, paper_seed = np.random.SeedSequence(style.seed).spawn(3)

    width, fixed_h = options.width, options.height
    size = float(style.size)
    shrunk = False
    rules: list[float] = []
    for _ in range(14):
        st = replace(style, size=size)
        if options.margin is not None:
            margin = options.margin
        elif fixed_h is not None:
            pad = 0.09 * min(width, fixed_h)
            margin = (pad, pad, pad, pad)
        else:
            margin = (size * 0.8, size * 0.8, size * 0.8, size * 0.8)
        top, _, bottom, _ = margin
        pitch = st.line_height * size

        def lay(**kw) -> Layout:
            return layout_text(
                paragraphs, st, width=width, height=fixed_h, margin=margin,
                rng=np.random.default_rng(layout_seed), **kw,
            )

        if info.ruled:
            limit = (fixed_h - bottom * 0.6) if fixed_h is not None else top + pitch * 400
            rules = []
            y = top + pitch
            while y <= limit:
                rules.append(y)
                y += pitch
            layout = lay(baselines=rules)
            if options.valign == "center" and fixed_h is not None and not layout.overflow:
                spare = len(rules) - layout.next_line
                if spare >= 2:
                    layout = lay(baselines=rules, first_line=int(spare * 0.45))
            overflow = layout.overflow
        else:
            layout = lay()
            overflow = fixed_h is not None and layout.content_height > fixed_h
            if options.valign == "center" and fixed_h is not None and not overflow:
                layout.translate(0, (fixed_h - layout.content_height) * 0.45)
        if not overflow or not options.fit or fixed_h is None:
            break
        size *= 0.93
        shrunk = True

    height = layout.height
    if info.ruled:
        # 종이의 줄은 글이 없는 곳에도 끝까지 그어져 있다.
        pitch = style.line_height * size
        rules = [r for r in rules if r < height]
        while rules and rules[-1] + pitch < height - pitch * 0.3:
            rules.append(rules[-1] + pitch)

    ink = render_ink(layout, pen, size, rng=np.random.default_rng(ink_seed), ss=options.ss)
    paper = make_paper(
        options.paper, width, height,
        rng=np.random.default_rng(paper_seed), scale=size,
        rules=rules, margin_x=margin[3] - size * 0.35,
    )
    image = composite(ink.alpha, ink.color, paper)
    return Page(image, ink.alpha, ink.color, layout, size, options.dpi, shrunk)
