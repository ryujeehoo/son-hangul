"""손글씨 배치와 래스터화.

폰트 글리프를 그대로 찍으면 같은 글자가 매번 똑같아서 바로 티가 난다. 그래서
글자를 놓을 때마다 다음을 무작위로 바꾼다.

- 글자 단위: 크기, 회전, 기울임, 기준선 위아래, 자간
- 획 단위: 윤곽선 전체를 부드러운 변위장(sin 합)으로 비튼다. 변위가 위치의
  함수라 획의 양쪽 윤곽이 같이 움직이므로 획 굵기는 유지되고 모양만 달라진다.
- 줄 단위: 기울기, 휘어짐, 왼쪽 여백, 줄마다 다른 크기, 뒤로 갈수록 조금 커짐
- 글 전체: 사람마다 다른 일정한 기울임(slant)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from .fonts import DEFAULT_FONT, FontChain
from .ink import Pen, apply_tone, shape_glyph


@dataclass
class Paragraph:
    text: str
    align: str = "left"  # left | right | center
    space_before: float = 0.0  # 줄 높이의 배수


@dataclass
class HandStyle:
    font: str = DEFAULT_FONT
    size: float = 56.0  # px. '가' 높이가 대략 size * 0.72
    line_height: float = 1.6  # size 의 배수
    tracking: float = 0.0  # 글자 사이 추가 간격(size 의 배수)
    messiness: float = 1.0  # 0 = 폰트 그대로, 1 = 기본, 2 = 많이 흐트러짐
    seed: int | None = None


@dataclass
class PlacedGlyph:
    ch: str
    contours: list[np.ndarray]  # 출력 픽셀 좌표, y 는 아래가 +


@dataclass
class Layout:
    glyphs: list[PlacedGlyph]
    width: int
    height: int
    baselines: list[float] = field(default_factory=list)
    missing: set[str] = field(default_factory=set)


@dataclass
class InkLayer:
    """종이에 올리기 전의 잉크. alpha 는 0..1, color 는 0..255 RGB."""

    alpha: np.ndarray
    color: tuple[int, int, int]
    layout: Layout


def _wrap(text: str, max_width: float, advance_of) -> list[str]:
    """어절(띄어쓰기) 단위로 줄을 나누고, 한 어절이 너무 길면 글자 단위로 자른다."""
    lines: list[str] = []
    for hard in text.split("\n"):
        words = hard.split(" ")
        line = ""
        for word in words:
            candidate = word if not line else f"{line} {word}"
            if advance_of(candidate) <= max_width or not line and advance_of(word) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            # 어절 하나가 한 줄보다 길면 글자 단위로 끊는다.
            for ch in word:
                if line and advance_of(line + ch) > max_width:
                    lines.append(line)
                    line = ""
                line += ch
        lines.append(line)
    return lines


class _Warp:
    """글자 하나에 적용할 부드러운 변위장."""

    def __init__(self, rng: np.random.Generator, messiness: float):
        def terms(n, amp, fmin, fmax):
            return [
                (
                    amp * rng.uniform(0.5, 1.0),
                    rng.uniform(fmin, fmax) * rng.choice([-1, 1]),
                    rng.uniform(fmin, fmax) * rng.choice([-1, 1]),
                    rng.uniform(0, 2 * math.pi),
                )
                for _ in range(n)
            ]

        m = messiness
        # 큰 흔들림(글자 모양이 달라짐) + 잔떨림(손 떨림)
        self.dx = terms(3, 0.020 * m, 0.5, 1.6) + terms(2, 0.0035 * m, 4.0, 8.0)
        self.dy = terms(3, 0.020 * m, 0.5, 1.6) + terms(2, 0.0035 * m, 4.0, 8.0)

    @staticmethod
    def _field(terms, p):
        out = np.zeros(len(p))
        for amp, fx, fy, ph in terms:
            out += amp * np.sin(2 * math.pi * (fx * p[:, 0] + fy * p[:, 1]) + ph)
        return out

    def __call__(self, p: np.ndarray) -> np.ndarray:
        return p + np.stack([self._field(self.dx, p), self._field(self.dy, p)], axis=1)


def layout_text(
    paragraphs: list[Paragraph],
    style: HandStyle,
    *,
    width: int,
    height: int | None = None,
    margin: tuple[float, float, float, float] = (40, 40, 40, 40),  # top, right, bottom, left
    baselines: list[float] | None = None,
    rng: np.random.Generator | None = None,
) -> Layout:
    """문단을 손글씨처럼 배치한다. baselines 를 주면(줄 노트) 그 줄 위에 쓴다."""
    rng = rng or np.random.default_rng(style.seed)
    chain = FontChain(style.font)
    size, m = style.size, style.messiness
    top, right, bottom, left = margin
    max_w = width - left - right
    line_h = style.line_height * size

    space = chain.lookup(" ")
    space_adv = (space.advance if space else 0.3) * size

    def advance_of(s: str) -> float:
        total = 0.0
        for ch in s:
            if ch == " ":
                total += space_adv * 1.08
                continue
            g = chain.lookup(ch)
            total += (g.advance if g else 0.5) * size + style.tracking * size
        return total

    # 글 전체에 일정한 기울임. 오른쪽으로 살짝 눕는 사람이 많다.
    slant = rng.uniform(-0.03, 0.10) * m

    # 줄 목록 만들기
    rows: list[tuple[str, str, float]] = []  # (text, align, space_before)
    for para in paragraphs:
        for i, line in enumerate(_wrap(para.text, max_w * 0.97, advance_of)):
            rows.append((line, para.align, para.space_before if i == 0 else 0.0))

    placed: list[PlacedGlyph] = []
    used_baselines: list[float] = []
    y = top + size * 0.95
    line_index = 0
    for text, align, space_before in rows:
        if baselines is not None:
            line_index += int(round(space_before))
            if line_index >= len(baselines):
                break
            base_y = baselines[line_index] - size * 0.08 + rng.normal(0, 0.03 * size) * m
            line_index += 1
        else:
            y += space_before * line_h
            base_y = y + rng.normal(0, 0.05 * size) * m
            y += line_h * (1 + rng.normal(0, 0.02) * m)

        slope = rng.normal(0, 0.010) * m  # dy/dx (아래가 +)
        bow = rng.normal(0, 0.05 * size) * m
        line_scale = 1 + rng.normal(0, 0.03) * m
        growth = rng.uniform(0.0, 0.05) * m  # 줄 끝으로 갈수록 커지는 정도
        indent = abs(rng.normal(0, 0.12 * size)) * m if align == "left" else 0.0

        line_glyphs: list[PlacedGlyph] = []
        x = 0.0
        total = max(advance_of(text), 1.0)
        for ch in text:
            t = min(x / total, 1.0)
            s = size * line_scale * (1 + growth * t)
            if ch == " ":
                x += space_adv * rng.uniform(0.85, 1.35) ** max(m, 0.01)
                continue
            glyph = chain.lookup(ch)
            if glyph is None:
                x += 0.5 * s
                continue
            scale = 1 + rng.normal(0, 0.045) * m
            rot = rng.normal(0, 0.035) * m - math.atan(slope)
            shear = slant + rng.normal(0, 0.04) * m
            dy = rng.normal(0, 0.035 * s) * m
            warp = _Warp(rng, m)

            contours = []
            all_pts = np.concatenate(glyph.contours) if glyph.contours else np.zeros((1, 2))
            cx = (all_pts[:, 0].min() + all_pts[:, 0].max()) / 2
            cy = (all_pts[:, 1].min() + all_pts[:, 1].max()) / 2
            cos_r, sin_r = math.cos(rot), math.sin(rot)
            transform = np.array([[cos_r, -sin_r], [sin_r, cos_r]]) @ np.array([[1, shear], [0, 1]]) * scale
            base_at_x = base_y + slope * x + bow * math.sin(math.pi * min(x / max_w, 1.0))
            for c in glyph.contours:
                q = warp(c) - (cx, cy)
                q = q @ transform.T + (cx, cy)
                px = x + q[:, 0] * s
                py = base_at_x + dy - q[:, 1] * s
                contours.append(np.stack([px, py], axis=1))
            line_glyphs.append(PlacedGlyph(ch, contours))
            jitter = rng.uniform(0.92, 1.06) ** max(m, 0.01)
            x += glyph.advance * s * scale * jitter + style.tracking * size

        if align == "right":
            offset = left + max_w - x - abs(rng.normal(0, 0.1 * size)) * m
        elif align == "center":
            offset = left + (max_w - x) / 2 + rng.normal(0, 0.1 * size) * m
        else:
            offset = left + indent
        for g in line_glyphs:
            g.contours = [c + (offset, 0) for c in g.contours]
        placed.extend(line_glyphs)
        used_baselines.append(base_y)

    if height is None:
        height = int(math.ceil((y if baselines is None else used_baselines[-1] + line_h) + bottom - line_h * 0.45))
        height = max(height, int(top + bottom + size))
    return Layout(placed, width, height, used_baselines, set(chain.missing))


def _rasterize_glyph(contours: list[np.ndarray], ss: int, pad: int):
    """글자 하나를 ss 배 해상도로 그린다(0 이 아닌 감김수 규칙). 출력 좌표 bbox 도 돌려준다."""
    pts = np.concatenate(contours)
    x0 = int(math.floor(pts[:, 0].min())) - pad
    y0 = int(math.floor(pts[:, 1].min())) - pad
    x1 = int(math.ceil(pts[:, 0].max())) + pad
    y1 = int(math.ceil(pts[:, 1].max())) + pad
    w, h = (x1 - x0) * ss, (y1 - y0) * ss
    winding = np.zeros((h, w), dtype=np.int16)
    for c in contours:
        q = (c - (x0, y0)) * ss
        area = 0.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], -1) - np.roll(q[:, 0], -1) * q[:, 1]))
        if area == 0:
            continue
        img = Image.new("1", (w, h), 0)
        ImageDraw.Draw(img).polygon([tuple(p) for p in q], fill=1)
        winding += np.asarray(img, dtype=np.int16) * (1 if area > 0 else -1)
    mask = (winding != 0).astype(np.float32)
    return mask, (x0, y0, x1, y1)


def render_ink(
    layout: Layout, pen: Pen, size: float, *, rng: np.random.Generator, ss: int = 3
) -> InkLayer:
    """배치된 글자를 펜 효과와 함께 잉크 레이어로 만든다."""
    alpha = np.zeros((layout.height, layout.width), dtype=np.float32)
    pad = int(math.ceil(abs(pen.weight) * size)) + 3
    for g in layout.glyphs:
        if not g.contours:
            continue
        mask, (x0, y0, x1, y1) = _rasterize_glyph(g.contours, ss, pad)
        mask = shape_glyph(mask, pen, size * ss, rng)
        small = Image.fromarray(mask, mode="F").resize((x1 - x0, y1 - y0), Image.Resampling.BOX)
        small = np.clip(np.asarray(small, dtype=np.float32), 0, 1)
        # 캔버스 밖으로 나간 부분 잘라내기
        cx0, cy0 = max(x0, 0), max(y0, 0)
        cx1, cy1 = min(x1, layout.width), min(y1, layout.height)
        if cx0 >= cx1 or cy0 >= cy1:
            continue
        part = small[cy0 - y0 : cy1 - y0, cx0 - x0 : cx1 - x0]
        region = alpha[cy0:cy1, cx0:cx1]
        alpha[cy0:cy1, cx0:cx1] = 1 - (1 - region) * (1 - part)
    alpha = apply_tone(alpha, pen, size, rng)
    return InkLayer(alpha, pen.color, layout)


def render_text(
    text: str | list[Paragraph],
    style: HandStyle,
    pen: Pen,
    *,
    width: int,
    height: int | None = None,
    margin: tuple[float, float, float, float] | None = None,
    baselines: list[float] | None = None,
    ss: int = 3,
) -> InkLayer:
    paragraphs = [Paragraph(text)] if isinstance(text, str) else text
    if margin is None:
        pad = style.size * 0.8
        margin = (pad, pad, pad, pad)
    seq = np.random.SeedSequence(style.seed)
    layout_rng, ink_rng = (np.random.default_rng(s) for s in seq.spawn(2))
    layout = layout_text(
        paragraphs, style, width=width, height=height, margin=margin, baselines=baselines, rng=layout_rng
    )
    return render_ink(layout, pen, style.size, rng=ink_rng, ss=ss)
