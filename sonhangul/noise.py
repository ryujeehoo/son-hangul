"""부드러운 무작위 필드(값 노이즈). 잉크 농도, 종이 결, 획 굵기 변화에 쓴다."""

from __future__ import annotations

import numpy as np
from PIL import Image


def value_noise(rng: np.random.Generator, width: int, height: int, cell: float) -> np.ndarray:
    """cell 픽셀 간격의 난수 격자를 부드럽게 늘린 0..1 필드."""
    gw = max(2, int(np.ceil(width / cell)) + 2)
    gh = max(2, int(np.ceil(height / cell)) + 2)
    grid = rng.random((gh, gw)).astype(np.float32)
    img = Image.fromarray(grid, mode="F").resize(
        (int(gw * cell), int(gh * cell)), Image.Resampling.BICUBIC
    )
    arr = np.asarray(img, dtype=np.float32)[:height, :width]
    return np.clip(arr, 0.0, 1.0)


def fractal_noise(
    rng: np.random.Generator, width: int, height: int, cell: float, octaves: int = 3
) -> np.ndarray:
    """여러 크기의 노이즈를 겹친 0..1 필드."""
    total = np.zeros((height, width), dtype=np.float32)
    amp, norm = 1.0, 0.0
    for i in range(octaves):
        c = max(1.0, cell / (2**i))
        total += amp * value_noise(rng, width, height, c)
        norm += amp
        amp *= 0.5
    return total / norm
