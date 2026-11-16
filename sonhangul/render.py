"""손글씨 배치와 래스터화.

폰트 글리프를 그대로 찍으면 같은 글자가 매번 똑같아서 바로 티가 난다. 그렇다고 글자마다
크기·기울기·높이를 따로따로 흔들면 손이 떨리는 악필처럼 보인다. 사람 글씨는 줄과 크기는
대체로 고르고, 개성은 일관된 버릇(자모 비율)에서 나온다. 그래서 세 가지를 나눠 다룬다.

- 버릇(habits): 초성·모음·받침·ㅇ 크기, 글자 폭, 기울임. 글 전체에 똑같이 적용한다.
- 흐트러짐(messiness): 쓸 때마다 달라지는 정도. 자모 크기와 윤곽선이 조금씩 달라지고,
  글자 높낮이는 글자마다 튀지 않고 앞 글자를 따라 천천히 오르내린다.
- 줄 흔들림(wobble): 줄이 기울거나 휘는 정도. 0 이면 자를 대고 쓴 것처럼 곧다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from .fonts import DEFAULT_FONT, FontChain
from .habits import Habits, apply_habits, segments_for
from .ink import Pen, apply_tone, shape_glyph


@dataclass
class Paragraph:
    text: str
    align: str = "left"  # left | right | center
    space_before: float = 0.0  # 줄 높이의 배수


@dataclass
class HandStyle:
    font: str = DEFAULT_FONT
    size: float = 56.0  # px. 글자 높이가 평균 size * 0.8 쯤 된다
    line_height: float = 1.6  # size 의 배수
    tracking: float = 0.0  # 글자 사이 추가 간격(size 의 배수)
    messiness: float = 1.0  # 0 = 폰트 그대로, 1 = 또박또박 쓴 사람, 2 = 흘려 쓴 사람, 3 = 급하게 쓴 쪽지
    wobble: float = 1.0  # 줄이 기울고 휘는 정도. 0 = 곧게
    habits: Habits = field(default_factory=Habits)  # 필체 버릇
    seed: int | None = None
    slant: float | None = None  # 글 전체 기울임. None 이면 시드로 정한다(같은 사람이 쓴 여러 장은 같은 값으로).


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
    overflow: bool = False  # 줄 노트에서 줄이 모자라 글이 잘렸는지
    next_line: int = 0  # 줄 노트에서 다음에 쓸 줄 번호
    content_height: float = 0.0  # 여백을 포함해 글이 차지한 높이

    def translate(self, dx: float, dy: float) -> None:
        for g in self.glyphs:
            g.contours = [c + (dx, dy) for c in g.contours]
        self.baselines = [b + dy for b in self.baselines]


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
        self.dx = terms(3, 0.011 * m, 0.5, 1.6) + terms(2, 0.0018 * m, 4.0, 8.0)
        self.dy = terms(3, 0.011 * m, 0.5, 1.6) + terms(2, 0.0018 * m, 4.0, 8.0)

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
    first_line: int = 0,
    rng: np.random.Generator | None = None,
) -> Layout:
    """문단을 손글씨처럼 배치한다. baselines 를 주면(줄 노트) first_line 번째 줄부터 그 위에 쓴다."""
    rng = rng or np.random.default_rng(style.seed)
    chain = FontChain(style.font)
    size, m, wob, habits = style.size, style.messiness, style.wobble, style.habits
    top, right, bottom, left = margin
    max_w = width - left - right
    line_h = style.line_height * size

    space = chain.lookup(" ")
    # 띄어쓰기 폭도 글자 폭 버릇을 따른다(길쭉하게 쓰는 사람은 띄어쓰기도 좁다).
    space_adv = (space.advance if space else 0.3) * size * style.habits.width

    def advance_of(s: str) -> float:
        total = 0.0
        for ch in s:
            if ch == " ":
                total += space_adv * 1.08
                continue
            total += habit_advance(ch) * size + style.tracking * size
        return total

    # 버릇을 입힌 글자 폭(줄바꿈 계산용). 쓸 때마다 달라지는 몫은 뺀 값이다.
    advance_cache: dict[str, float] = {}

    def habit_advance(ch: str) -> float:
        if ch not in advance_cache:
            g = chain.lookup(ch)
            if g is None:
                advance_cache[ch] = 0.5
            else:
                advance_cache[ch] = apply_habits(
                    ch, g.contours, g.advance, habits, segments_for(ch, g), rng, 0.0
                )[1]
        return advance_cache[ch]

    # 글 전체에 일정한 기울임. 오른쪽으로 살짝 눕는 사람이 많다.
    slant = rng.uniform(-0.02, 0.06) * min(m, 1.5)
    if habits.slant is not None:
        slant = habits.slant
    if style.slant is not None:
        slant = style.slant

    # 줄 목록 만들기
    rows: list[tuple[str, str, float]] = []  # (text, align, space_before)
    for para in paragraphs:
        for i, line in enumerate(_wrap(para.text, max_w * 0.97, advance_of)):
            rows.append((line, para.align, para.space_before if i == 0 else 0.0))

    placed: list[PlacedGlyph] = []
    used_baselines: list[float] = []
    y = top + size * 0.95
    line_index = first_line
    overflow = False
    for text, align, space_before in rows:
        if baselines is not None:
            line_index += int(round(space_before))
            if line_index >= len(baselines):
                overflow = True
                break
            # 한글은 받침이 기준선 아래로 내려가므로, 글자 밑이 줄 바로 위에 오도록 올려 쓴다.
            base_y = baselines[line_index] + (chain.primary.descent - 0.05) * size + rng.normal(0, 0.012 * size) * wob
            line_index += 1
        else:
            y += space_before * line_h
            base_y = y + rng.normal(0, 0.02 * size) * wob
            y += line_h * (1 + rng.normal(0, 0.008) * wob)

        slope = rng.normal(0, 0.0035) * wob  # dy/dx (아래가 +)
        bow = rng.normal(0, 0.015 * size) * wob
        line_scale = 1 + rng.normal(0, 0.012) * m
        growth = rng.uniform(0.0, 0.02) * m  # 줄 끝으로 갈수록 커지는 정도
        indent = abs(rng.normal(0, 0.05 * size)) * wob if align == "left" else 0.0
        # 줄을 따라 기준선이 천천히 오르내린다(글자마다 따로 튀는 것과는 별개).
        drift_amp = rng.normal(0, 0.012 * size) * wob
        drift_len = rng.uniform(6.0, 12.0) * size
        drift_phase = rng.uniform(0, 2 * math.pi)
        # 높이와 크기의 큰 몫은 앞 글자를 따라 천천히 변한다. 글자마다 따로 튀면 떨리는 글씨가 된다.
        ar_dy = ar_scale = 0.0

        line_glyphs: list[PlacedGlyph] = []
        x = 0.0
        total = max(advance_of(text), 1.0)
        for ch in text:
            t = min(x / total, 1.0)
            s = size * line_scale * (1 + growth * t)
            if ch == " ":
                x += space_adv * rng.uniform(0.92, 1.16) ** max(m, 0.01)
                continue
            glyph = chain.lookup(ch)
            if glyph is None:
                x += 0.5 * s
                continue
            ar_dy = 0.75 * ar_dy + rng.normal(0, 0.66)
            ar_scale = 0.75 * ar_scale + rng.normal(0, 0.66)
            scale = 1 + (0.014 * ar_scale + rng.normal(0, 0.008)) * m
            rot = rng.normal(0, 0.010) * m - math.atan(slope)
            shear = slant + rng.normal(0, 0.012) * m
            dy = (0.012 * ar_dy + rng.normal(0, 0.006)) * s * m
            warp = _Warp(rng, m)
            shaped, advance = apply_habits(
                ch, glyph.contours, glyph.advance, habits, segments_for(ch, glyph), rng, 0.025 * m
            )

            contours = []
            all_pts = np.concatenate(shaped) if shaped else np.zeros((1, 2))
            cx = (all_pts[:, 0].min() + all_pts[:, 0].max()) / 2
            cy = (all_pts[:, 1].min() + all_pts[:, 1].max()) / 2
            cos_r, sin_r = math.cos(rot), math.sin(rot)
            transform = np.array([[cos_r, -sin_r], [sin_r, cos_r]]) @ np.array([[1, shear], [0, 1]]) * scale
            base_at_x = (
                base_y
                + slope * x
                + bow * math.sin(math.pi * min(x / max_w, 1.0))
                + drift_amp * math.sin(2 * math.pi * x / drift_len + drift_phase)
            )
            for c in shaped:
                q = warp(c) - (cx, cy)
                q = q @ transform.T + (cx, cy)
                px = x + q[:, 0] * s
                py = base_at_x + dy - q[:, 1] * s
                contours.append(np.stack([px, py], axis=1))
            line_glyphs.append(PlacedGlyph(ch, contours))
            jitter = rng.uniform(0.97, 1.03) ** max(m, 0.01)
            x += advance * s * scale * jitter + style.tracking * size

        if align == "right":
            offset = left + max_w - x - abs(rng.normal(0, 0.04 * size)) * wob
        elif align == "center":
            offset = left + (max_w - x) / 2 + rng.normal(0, 0.04 * size) * wob
        else:
            offset = left + indent
        for g in line_glyphs:
            g.contours = [c + (offset, 0) for c in g.contours]
        placed.extend(line_glyphs)
        used_baselines.append(base_y)

    if baselines is None:
        end = y
    else:
        end = (used_baselines[-1] if used_baselines else top) + line_h
    content_height = max(end + bottom - line_h * 0.45, top + bottom + size)
    if height is None:
        height = int(math.ceil(content_height))
    return Layout(
        placed, width, height, used_baselines, set(chain.missing), overflow, line_index, content_height
    )


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
    # 필압은 글자마다 따로 튀지 않고 앞 글자를 따라 천천히 변한다.
    bias = 0.0
    for g in layout.glyphs:
        if not g.contours:
            continue
        bias = 0.8 * bias + rng.normal(0, 0.6)
        mask, (x0, y0, x1, y1) = _rasterize_glyph(g.contours, ss, pad)
        mask = shape_glyph(mask, pen, size * ss, rng, bias)
        small = Image.fromarray(mask).resize((x1 - x0, y1 - y0), Image.Resampling.BOX)
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
