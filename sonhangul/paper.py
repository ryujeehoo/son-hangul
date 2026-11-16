"""종이 배경과 잉크 합성."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from .errors import SonError
from .noise import fractal_noise, value_noise


@dataclass(frozen=True)
class PaperInfo:
    key: str
    name: str
    ruled: bool = False  # 줄이 있어서 글씨가 줄을 따라가야 하는 종이
    tooth: float = 0.0  # 종이 결이 잉크를 먹는 정도


PAPERS: dict[str, PaperInfo] = {
    p.key: p
    for p in [
        PaperInfo("blank", "흰 바탕(인쇄용: 실제 카드나 편지지에 찍을 때)"),
        PaperInfo("plain", "무지(미색 종이 결)", tooth=0.05),
        PaperInfo("lined", "줄 노트", ruled=True, tooth=0.05),
        PaperInfo("grid", "모눈", ruled=True, tooth=0.05),
        PaperInfo("kraft", "크라프트", tooth=0.16),
        PaperInfo("aged", "낡은 종이(게임 소품용)", tooth=0.12),
        PaperInfo("transparent", "배경 없음(투명 PNG, 게임 텍스처용)"),
    ]
}

DEFAULT_PAPER = "plain"


def get_paper(key: str) -> PaperInfo:
    if key not in PAPERS:
        raise SonError(f"모르는 종이입니다: {key}\n쓸 수 있는 종이: {', '.join(PAPERS)}")
    return PAPERS[key]


@dataclass
class Paper:
    info: PaperInfo
    rgb: np.ndarray | None  # (H, W, 3) float32 0..255. transparent 면 None
    grain: np.ndarray | None  # (H, W) 0..1. 잉크가 덜 묻는 정도


def _fiber(rng: np.random.Generator, w: int, h: int, length: float, thickness: float) -> np.ndarray:
    """가로로 길쭉한 섬유 결 노이즈(0..1)."""
    gw = max(2, int(w / length) + 2)
    gh = max(2, int(h / thickness) + 2)
    grid = rng.random((gh, gw)).astype(np.float32)
    img = Image.fromarray(grid).resize((w, h), Image.Resampling.BICUBIC)
    return np.clip(np.asarray(img, dtype=np.float32), 0, 1)


def _edge_distance(w: int, h: int) -> np.ndarray:
    """가장 가까운 가장자리까지의 거리(짧은 변의 절반을 1 로)."""
    ys = np.minimum(np.arange(h), np.arange(h)[::-1]).astype(np.float32)[:, None]
    xs = np.minimum(np.arange(w), np.arange(w)[::-1]).astype(np.float32)[None, :]
    return np.minimum(xs, ys) / (min(w, h) / 2)


def make_paper(
    key: str,
    width: int,
    height: int,
    *,
    rng: np.random.Generator,
    scale: float = 56.0,
    rules: list[float] | None = None,
    margin_x: float | None = None,
) -> Paper:
    """종이를 만든다. scale 은 글씨 크기(px)로, 결의 굵기를 여기에 맞춘다.

    rules 는 줄을 그을 y 좌표들(줄 노트, 모눈).
    """
    info = get_paper(key)
    w, h = width, height
    if key == "transparent":
        return Paper(info, None, None)
    if key == "blank":
        return Paper(info, np.full((h, w, 3), 255.0, dtype=np.float32), None)

    fine = value_noise(rng, w, h, max(1.5, scale * 0.03))
    cloud = fractal_noise(rng, w, h, scale * 4.0, octaves=3)
    fiber = _fiber(rng, w, h, scale * 0.9, max(1.2, scale * 0.02))

    if key in ("plain", "lined", "grid"):
        base = np.array([251, 249, 243], dtype=np.float32)
        shade = 1.0 - 0.018 * fine - 0.02 * cloud - 0.012 * fiber
        grain = 0.5 * fine + 0.5 * fiber
    elif key == "kraft":
        base = np.array([201, 170, 126], dtype=np.float32)
        speck = rng.random((h, w), dtype=np.float32)
        short = _fiber(rng, w, h, scale * 0.25, max(1.0, scale * 0.012))
        shade = 1.0 - 0.06 * fine - 0.07 * cloud - 0.035 * fiber - 0.06 * short - 0.10 * (speck > 0.992)
        grain = 0.35 * fine + 0.65 * fiber
    elif key == "aged":
        base = np.array([233, 216, 176], dtype=np.float32)
        blotch = fractal_noise(rng, w, h, min(w, h) / 2.5, octaves=4)
        edge = np.clip(_edge_distance(w, h) / 0.22, 0, 1)
        # 가장자리로 갈수록 누렇게 타들어 간 느낌. 경계가 들쭉날쭉하도록 노이즈를 섞는다.
        burn = np.clip(1.0 - edge + 0.5 * (blotch - 0.5), 0, 1) ** 2
        shade = 1.0 - 0.05 * fine - 0.16 * np.clip(blotch - 0.35, 0, 1) - 0.06 * fiber - 0.30 * burn
        grain = 0.5 * fine + 0.5 * fiber
    else:  # pragma: no cover - PAPERS 와 어긋났을 때만
        raise SonError(f"종이를 만들 수 없습니다: {key}")

    rgb = base[None, None, :] * shade[..., None]

    if key == "aged":
        # 물이나 커피가 마른 자국: 안쪽은 옅고 테두리만 조금 진한 타원 몇 개
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        tint = np.array([0.80, 0.70, 0.52], dtype=np.float32)
        for _ in range(int(rng.integers(2, 5))):
            cx, cy = rng.uniform(0, w), rng.uniform(0, h)
            rx, ry = rng.uniform(0.08, 0.22, size=2) * min(w, h)
            d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
            d = d + 0.45 * (blotch - 0.5) + 0.10 * (cloud - 0.5)
            ring = np.exp(-((d - 1.0) / 0.06) ** 2) * 0.07 * (0.4 + 1.2 * cloud) + np.clip(1.0 - d, 0, 1) ** 0.5 * 0.035
            rgb = rgb * (1.0 - ring[..., None] * (1.0 - tint[None, None, :]) * 3.0)

    rgb = np.clip(rgb, 0, 255).astype(np.float32)

    if info.ruled and rules:
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        line_w = max(1, round(scale * 0.022))
        if key == "lined":
            color = (120, 150, 190, 150)
            for y in rules:
                draw.line([(0, y), (w, y)], fill=color, width=line_w)
            if margin_x is not None and margin_x > scale * 0.4:
                draw.line([(margin_x, 0), (margin_x, h)], fill=(214, 110, 110, 140), width=line_w)
        else:  # grid: 줄 간격을 둘로 나눈 칸
            color = (130, 160, 190, 110)
            pitch = (rules[1] - rules[0]) if len(rules) > 1 else scale * 1.6
            cell = pitch / 2
            y = rules[0] % cell
            while y < h:
                draw.line([(0, y), (w, y)], fill=color, width=line_w)
                y += cell
            x = cell / 2
            while x < w:
                draw.line([(x, 0), (x, h)], fill=color, width=line_w)
                x += cell
        ov = np.asarray(overlay, dtype=np.float32)
        a = ov[..., 3:4] / 255.0
        # 인쇄된 줄도 종이 결을 따라 조금 옅어졌다 진해졌다 한다.
        a = a * (0.8 + 0.2 * fine[..., None])
        rgb = rgb * (1 - a) + ov[..., :3] * a

    return Paper(info, rgb.astype(np.float32), grain.astype(np.float32))


def composite(alpha: np.ndarray, color: tuple[int, int, int], paper: Paper) -> Image.Image:
    """잉크를 종이에 올린다. 투명 종이면 RGBA, 아니면 RGB 이미지."""
    if paper.rgb is None:
        h, w = alpha.shape
        out = np.empty((h, w, 4), dtype=np.uint8)
        out[..., :3] = color
        out[..., 3] = np.uint8(np.clip(alpha, 0, 1) * 255 + 0.5)
        return Image.fromarray(out, "RGBA")
    a = alpha
    if paper.grain is not None and paper.info.tooth > 0:
        a = a * (1.0 - paper.info.tooth * paper.grain)
    ink = np.asarray(color, dtype=np.float32) / 255.0
    # 곱하기 합성: 잉크는 종이를 덮는 게 아니라 어둡게 물들인다.
    rgb = paper.rgb * (1.0 - a[..., None] * (1.0 - ink[None, None, :]))
    return Image.fromarray(np.uint8(np.clip(rgb, 0, 255) + 0.5), "RGB")
