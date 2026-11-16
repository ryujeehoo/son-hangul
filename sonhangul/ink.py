"""펜 프리셋과 잉크 효과.

글자 모양(획 굵기, 윤곽 거칠기)은 글자 하나를 크게 그린 상태에서 손보고(shape_glyph),
진하기(얼룩, 볼펜 끊김, 연필 결, 번짐, 잉크 고임)는 다 모은 뒤 한 번에 입힌다(apply_tone).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from .errors import SonError
from .noise import fractal_noise, value_noise


@dataclass(frozen=True)
class Pen:
    key: str
    name: str
    color: tuple[int, int, int]
    weight: float = 0.0  # 획 굵기 보정(em). + 굵게, - 가늘게
    pressure: float = 0.004  # 필압에 따라 굵기가 변하는 폭(em)
    rough: float = 0.1  # 윤곽 거칠기 0..1
    opacity: float = 0.95  # 기본 진하기
    tone_var: float = 0.15  # 종이 전체에 걸친 농도 얼룩
    skip: float = 0.0  # 볼펜 잉크 끊김
    grain: float = 0.0  # 연필 흑연 결
    bleed: float = 0.0  # 번짐 반경(em)
    pool: float = 0.0  # 획 가장자리에 잉크가 고이는 정도


PENS: dict[str, Pen] = {
    p.key: p
    for p in [
        Pen("ballpoint", "볼펜(검정)", (28, 28, 36), weight=-0.002, pressure=0.005, rough=0.18,
            opacity=0.90, tone_var=0.22, skip=0.35),
        Pen("ballpoint-blue", "볼펜(파랑)", (24, 46, 128), weight=-0.002, pressure=0.005, rough=0.18,
            opacity=0.88, tone_var=0.22, skip=0.35),
        Pen("gel", "젤펜", (14, 14, 20), weight=0.004, pressure=0.004, rough=0.06,
            opacity=0.98, tone_var=0.06, pool=0.10),
        Pen("fountain", "만년필", (20, 32, 78), weight=0.005, pressure=0.007, rough=0.08,
            opacity=0.96, tone_var=0.26, bleed=0.006, pool=0.38),
        Pen("pencil", "연필", (62, 62, 66), weight=0.002, pressure=0.006, rough=0.45,
            opacity=0.74, tone_var=0.25, grain=0.60),
        Pen("marker", "사인펜", (18, 18, 22), weight=0.016, pressure=0.004, rough=0.10,
            opacity=0.94, tone_var=0.10, bleed=0.010, pool=0.20),
    ]
}

DEFAULT_PEN = "gel"


def get_pen(key: str, color: tuple[int, int, int] | None = None) -> Pen:
    if key not in PENS:
        raise SonError(f"모르는 펜입니다: {key}\n쓸 수 있는 펜: {', '.join(PENS)}")
    pen = PENS[key]
    if color is not None:
        pen = Pen(**{**pen.__dict__, "color": color})
    return pen


def parse_color(text: str) -> tuple[int, int, int]:
    """'#1a2b3c' 또는 '26,43,60' 을 RGB 로."""
    s = text.strip()
    try:
        if s.startswith("#") and len(s) == 7:
            return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
        parts = [int(p) for p in s.split(",")]
        if len(parts) == 3 and all(0 <= p <= 255 for p in parts):
            return (parts[0], parts[1], parts[2])
    except ValueError:
        pass
    raise SonError(f"색을 이해하지 못했습니다: {text} (예: #1a2b3c 또는 26,43,60)")


def _blur(arr: np.ndarray, radius: float) -> np.ndarray:
    """0..1 배열을 가우시안으로 흐린다."""
    if radius <= 0.05:
        return arr
    img = Image.fromarray(np.uint8(np.clip(arr, 0, 1) * 255 + 0.5))
    out = img.filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(out, dtype=np.float32) / 255.0


def shape_glyph(
    mask: np.ndarray, pen: Pen, size_px: float, rng: np.random.Generator, bias: float = 0.0
) -> np.ndarray:
    """글자 하나의 획 굵기와 윤곽을 손본다. mask 는 확대된 해상도의 0/1 배열.

    마스크를 흐린 뒤 문턱값으로 다시 자르면 획이 굵어지거나 가늘어진다. 문턱값을
    위치마다 다르게 주어 한 글자 안에서도 힘이 들어간 곳과 빠진 곳이 생기게 한다.
    bias 는 앞 글자에서 이어지는 필압(표준편차 1 안팎)이다.
    """
    h, w = mask.shape
    sigma = max(1.2, 0.011 * size_px)
    soft = _blur(mask, sigma)

    # 앞 글자에서 이어지는 필압 + 글자 안에서 천천히 변하는 필압
    offset = pen.weight + pen.pressure * 0.3 * bias
    offset_map = offset + pen.pressure * 1.0 * (value_noise(rng, w, h, max(4.0, 0.30 * size_px)) - 0.5)
    threshold = 0.5 - (offset_map * size_px) / (2.5 * sigma)
    if pen.rough > 0:
        threshold = threshold + pen.rough * 0.22 * (value_noise(rng, w, h, max(1.5, 0.018 * size_px)) - 0.5)
    threshold = np.clip(threshold, 0.10, 0.90)
    return np.clip((soft - threshold) / 0.12 + 0.5, 0.0, 1.0).astype(np.float32)


def apply_tone(alpha: np.ndarray, pen: Pen, size: float, rng: np.random.Generator) -> np.ndarray:
    """다 그린 잉크에 농도 변화를 입힌다. alpha 는 출력 해상도의 0..1 배열."""
    h, w = alpha.shape
    out = alpha

    if pen.bleed > 0:
        spread = _blur(out, pen.bleed * size)
        out = np.maximum(out, np.clip(spread * 1.35, 0, 1) * 0.85)

    if pen.pool > 0:
        # 획 안쪽은 조금 옅고 가장자리는 진하다(물기 많은 잉크가 마르며 가장자리로 몰림).
        inner = _blur(out, max(0.6, 0.012 * size))
        edge = np.clip(1.0 - inner, 0, 1)
        out = out * (1.0 - pen.pool * 0.45 * (1.0 - edge) ** 2)

    density = 1.0 - pen.tone_var * fractal_noise(rng, w, h, size * 1.8, octaves=3)
    if pen.tone_var > 0:
        # 글자 몇 개 단위의 잔얼룩(펜을 누르는 힘이 들쭉날쭉한 느낌)
        density = density * (1.0 - pen.tone_var * 0.5 * value_noise(rng, w, h, max(2.0, size * 0.35)))
    out = out * pen.opacity * density

    if pen.skip > 0:
        # 볼펜: 잉크가 고르게 안 나와 가느다란 결이 생긴다.
        streak = value_noise(rng, w, h, max(1.5, size * 0.035))
        gaps = np.clip((0.42 - streak) / 0.25, 0, 1)
        out = out * (1.0 - pen.skip * gaps)

    if pen.grain > 0:
        # 연필: 종이 결에 걸려 흑연이 듬성듬성 묻는다.
        speck = rng.random((h, w), dtype=np.float32)
        coarse = value_noise(rng, w, h, max(1.5, size * 0.03))
        tooth = 0.55 * speck + 0.45 * coarse
        out = out * (1.0 - pen.grain * np.clip((tooth - 0.25) / 0.6, 0, 1))

    return np.clip(out, 0.0, 1.0).astype(np.float32)
