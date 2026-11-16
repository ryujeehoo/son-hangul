"""필체 버릇: 한 사람이 일관되게 갖는 글씨 습관.

사람 글씨가 서로 달라 보이는 까닭은 글자마다 아무렇게나 흔들려서가 아니라, 초성을 크게
쓰거나 모음을 짧게 긋거나 ㅇ을 작게 쓰는 식의 버릇이 글 전체에 똑같이 나타나기
때문이다. 손글씨 폰트 7종을 재 보면 ㅇ 크기는 1.7배, 초성 높이는 1.4배, 받침 너비는
1.5배까지 차이가 나지만 글자 전체의 가로세로 비율은 1.1배도 차이 나지 않는다
(docs/handwriting-analysis.md).

여기서는 글리프를 초성·중성·종성으로 나눠(jamo.segment) 자모마다 크기를 바꾼다.
획이 붙어 있어 나눌 수 없는 글자는 자모가 놓이는 자리를 기준으로 부드럽게 늘이고 줄인다.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

import numpy as np

from .errors import SonError
from .jamo import _ANCHORS, HORIZONTAL, VERTICAL, Segments, decompose, layout_of, segment


@dataclass(frozen=True)
class Habits:
    cho: float = 1.0  # 초성 크기
    ieung: float = 1.0  # ㅇ 크기(초성, 받침 모두)
    vowel: float = 1.0  # 모음 전체 크기
    vowel_v: float = 1.0  # 세로로 서는 모음(ㅏㅓㅣ)의 길이
    vowel_h: float = 1.0  # 가로로 눕는 모음(ㅗㅜㅡ)의 너비
    jong: float = 1.0  # 받침 크기
    jong_drop: float = 0.0  # 받침을 아래로 내려 쓰는 정도(em)
    width: float = 1.0  # 글자 폭. 1 보다 작으면 길쭉하게
    slant: float | None = None  # 기울임. None 이면 시드로 조금만
    spacing: float = 0.0  # 글자 사이를 더 띄우는 정도(em)

    @property
    def plain(self) -> bool:
        """자모를 건드릴 일이 없는지."""
        return (
            self.cho == self.ieung == self.vowel == self.vowel_v == self.vowel_h == self.jong == 1.0
            and self.jong_drop == 0.0
        )


PRESETS: dict[str, tuple[str, dict[str, float]]] = {
    "none": ("버릇 없음(폰트 그대로)", {}),
    "big-cho": ("자음을 크게 쓰는 사람", {"cho": 1.22, "vowel": 0.94}),
    "small-cho": ("자음을 작게 쓰는 사람", {"cho": 0.82}),
    "small-vowel": ("모음을 짧고 작게 쓰는 사람", {"vowel_v": 0.72, "vowel_h": 0.80}),
    "long-vowel": ("모음을 길게 긋는 사람", {"vowel_v": 1.18, "vowel_h": 1.15}),
    "big-ieung": ("ㅇ을 크고 둥글게 쓰는 사람", {"ieung": 1.35}),
    "small-ieung": ("ㅇ을 점처럼 작게 쓰는 사람", {"ieung": 0.62}),
    "big-jong": ("받침을 크게 쓰는 사람", {"jong": 1.25, "jong_drop": 0.02}),
    "small-jong": ("받침을 작게 쓰는 사람", {"jong": 0.76}),
    "narrow": ("길쭉하게 쓰는 사람", {"width": 0.86}),
    "wide": ("납작하게 쓰는 사람", {"width": 1.14, "vowel_v": 0.90}),
    "slanted": ("오른쪽으로 눕혀 쓰는 사람", {"slant": 0.22}),
    "upright": ("꼿꼿하게 세워 쓰는 사람", {"slant": 0.0}),
}

# random 버릇을 뽑는 범위. 폰트 7종에서 잰 사람 사이의 차이보다 조금 좁게 잡았다.
_RANDOM_RANGES = {
    "cho": (0.86, 1.20),
    "ieung": (0.70, 1.32),
    "vowel_v": (0.80, 1.12),
    "vowel_h": (0.82, 1.15),
    "jong": (0.82, 1.20),
    "jong_drop": (0.0, 0.03),
    "width": (0.90, 1.08),
    "slant": (-0.02, 0.16),
    "spacing": (-0.015, 0.035),
}


def random_habits(seed: int | None) -> Habits:
    """시드로 한 사람의 버릇을 정한다. 같은 시드는 늘 같은 사람이다."""
    rng = np.random.default_rng(np.random.SeedSequence([0x5EED, seed]) if seed is not None else None)
    return Habits(**{k: float(rng.uniform(lo, hi)) for k, (lo, hi) in _RANDOM_RANGES.items()})


def get_habits(names: str | None, seed: int | None = None, **overrides: float | None) -> Habits:
    """'big-cho,small-vowel' 처럼 쉼표로 여러 버릇을 겹칠 수 있다. overrides 는 숫자로 직접 준 값."""
    habits = Habits()
    for name in [n.strip() for n in (names or "none").split(",") if n.strip()]:
        if name == "random":
            habits = random_habits(seed)
            continue
        if name not in PRESETS:
            raise SonError(f"모르는 버릇입니다: {name}\n쓸 수 있는 버릇: random, {', '.join(PRESETS)}")
        habits = replace(habits, **PRESETS[name][1])
    given = {k: v for k, v in overrides.items() if v is not None}
    unknown = set(given) - {f.name for f in fields(Habits)}
    if unknown:
        raise SonError(f"모르는 버릇 값입니다: {', '.join(sorted(unknown))}")
    for key, value in given.items():
        if key not in ("slant", "spacing", "jong_drop") and not 0.4 <= value <= 2.0:
            raise SonError(f"{key} 는 0.4 ~ 2.0 사이로 주세요: {value}")
    return replace(habits, **given)


def _role_scales(habits: Habits, cho: str, jung: str, jong: str, wobble: dict[str, float]):
    """자모별 (가로 배율, 세로 배율, 세로 이동)."""
    c = habits.cho * (habits.ieung if cho == "ㅇ" else 1.0) * wobble["cho"]
    if jung in VERTICAL:
        jx, jy = habits.vowel, habits.vowel * habits.vowel_v
    elif jung in HORIZONTAL:
        jx, jy = habits.vowel * habits.vowel_h, habits.vowel
    else:
        jx, jy = habits.vowel * habits.vowel_h**0.5, habits.vowel * habits.vowel_v**0.5
    t = habits.jong * (habits.ieung if jong == "ㅇ" else 1.0) * wobble["jong"]
    return {
        "cho": (c, c, 0.0),
        "jung": (jx * wobble["jung"], jy * wobble["jung"], 0.0),
        "jong": (t, t, -habits.jong_drop),
    }


def apply_habits(
    ch: str,
    contours: list[np.ndarray],
    advance: float,
    habits: Habits,
    segments: Segments | None,
    rng: np.random.Generator,
    variation: float = 0.0,
) -> tuple[list[np.ndarray], float]:
    """글자 하나에 버릇을 입힌다. contours 는 em 단위(y 는 위가 +).

    variation 은 같은 사람이라도 쓸 때마다 자모 크기가 조금씩 달라지는 정도(표준편차).
    """
    if not contours:
        return contours, advance
    parts = decompose(ch)
    out = contours
    if parts is not None and (not habits.plain or variation > 0):
        cho, jung, jong = parts
        wobble = {r: float(np.exp(rng.normal(0, variation))) if variation > 0 else 1.0 for r in ("cho", "jung", "jong")}
        scales = _role_scales(habits, cho, jung, jong, wobble)
        before = np.concatenate(contours)
        lo, hi = before.min(axis=0), before.max(axis=0)
        if segments is not None:
            out = list(contours)
            for role in ("cho", "jung", "jong"):
                idx = getattr(segments, role)
                sx, sy, dy = scales[role]
                if not idx or (sx == 1.0 and sy == 1.0 and dy == 0.0):
                    continue
                pts = np.concatenate([contours[i] for i in idx])
                center = (pts.min(axis=0) + pts.max(axis=0)) / 2
                for i in idx:
                    out[i] = (contours[i] - center) * (sx, sy) + center + (0.0, dy)
        else:
            # 획이 붙어 있어 못 나눈 글자: 자모가 놓이는 자리를 중심으로 부드럽게 늘이고 줄인다.
            size = np.maximum(hi - lo, 1e-6)
            anchors = _ANCHORS[(layout_of(jung), bool(jong))]
            sigma = 0.24
            weights, moves = [], []
            for role, spots in anchors.items():
                sx, sy, dy = scales[role]
                spots_em = [lo + np.array(s) * size for s in spots]
                center = np.mean(spots_em, axis=0)
                weights.append(spots_em)
                moves.append((center, np.array([sx, sy]), dy))
            out = []
            for c in contours:
                u = (c - lo) / size
                w = []
                for spots_em in weights:
                    d2 = np.min([np.sum((u - (s - lo) / size) ** 2, axis=1) for s in spots_em], axis=0)
                    w.append(np.exp(-d2 / (2 * sigma**2)))
                w = np.array(w)
                w = w / np.maximum(w.sum(axis=0), 1e-9)
                disp = np.zeros_like(c)
                for k, (center, s, dy) in enumerate(moves):
                    disp += w[k][:, None] * ((c - center) * (s - 1.0) + (0.0, dy))
                out.append(c + disp)
        # 커진 만큼 글자가 차지하는 폭도 늘리고, 왼쪽으로 튀어나온 만큼 밀어 준다.
        after = np.concatenate(out)
        lo2, hi2 = after.min(axis=0), after.max(axis=0)
        shift = max(0.0, lo[0] - lo2[0])
        if shift:
            out = [c + (shift, 0.0) for c in out]
        advance = max(advance * 0.6, advance + ((hi2[0] - lo2[0]) - (hi[0] - lo[0])))
    if habits.width != 1.0:
        out = [c * (habits.width, 1.0) for c in out]
        advance *= habits.width
    return out, advance + habits.spacing


def segments_for(ch: str, glyph) -> Segments | None:
    """글리프에 자모 나눈 결과를 붙여 두고 다시 쓴다(느린 계산이라)."""
    cached = getattr(glyph, "_segments", False)
    if cached is False:
        cached = segment(ch, glyph.contours) if decompose(ch) else None
        glyph._segments = cached
    return cached
