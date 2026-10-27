"""손글씨 폰트 목록, 내려받기, 글리프 윤곽선 읽기.

폰트 파일은 저장소에 넣지 않고 Google Fonts 저장소(SIL OFL)에서 내려받는다.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

from .config import font_dir
from .errors import SonError

GOOGLE_FONTS_RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl"


@dataclass(frozen=True)
class FontInfo:
    key: str
    name: str
    filename: str
    path: str  # google/fonts 저장소 안의 경로
    license: str
    note: str


FONTS: dict[str, FontInfo] = {
    f.key: f
    for f in [
        FontInfo("nanum-pen", "나눔손글씨 펜 (Nanum Pen Script)", "NanumPenScript-Regular.ttf",
                 "nanumpenscript/NanumPenScript-Regular.ttf", "SIL OFL 1.1",
                 "가늘고 빠르게 흘려 쓴 펜 글씨. 기본값."),
        FontInfo("nanum-brush", "나눔손글씨 붓 (Nanum Brush Script)", "NanumBrushScript-Regular.ttf",
                 "nanumbrushscript/NanumBrushScript-Regular.ttf", "SIL OFL 1.1",
                 "붓펜 느낌. 굵고 획 끝이 날림."),
        FontInfo("gaegu", "개구 (Gaegu)", "Gaegu-Regular.ttf",
                 "gaegu/Gaegu-Regular.ttf", "SIL OFL 1.1",
                 "동글동글한 메모 글씨. 자주 쓰는 2,350자만 있어 나머지는 다른 폰트로 채움."),
        FontInfo("hi-melody", "하이멜로디 (Hi Melody)", "HiMelody-Regular.ttf",
                 "himelody/HiMelody-Regular.ttf", "SIL OFL 1.1",
                 "또박또박 쓴 학생 글씨."),
        FontInfo("gamja", "감자꽃 (Gamja Flower)", "GamjaFlower-Regular.ttf",
                 "gamjaflower/GamjaFlower-Regular.ttf", "SIL OFL 1.1",
                 "귀엽고 둥근 글씨."),
        FontInfo("poor-story", "푸어스토리 (Poor Story)", "PoorStory-Regular.ttf",
                 "poorstory/PoorStory-Regular.ttf", "SIL OFL 1.1",
                 "삐뚤빼뚤한 낙서 글씨."),
        FontInfo("single-day", "싱글데이 (Single Day)", "SingleDay-Regular.ttf",
                 "singleday/SingleDay-Regular.ttf", "SIL OFL 1.1",
                 "얇은 사인펜 글씨."),
    ]
}

DEFAULT_FONT = "nanum-pen"
# 글자가 없을 때 차례로 찾아볼 폰트. 완성형 11,172자를 거의 다 가진 폰트 위주.
FALLBACK_ORDER = ["nanum-pen", "hi-melody", "gamja", "poor-story", "single-day"]


def font_path(key: str) -> Path:
    if key not in FONTS:
        raise SonError(f"모르는 폰트입니다: {key}\n쓸 수 있는 폰트: {', '.join(FONTS)}")
    return font_dir() / FONTS[key].filename


def download_font(key: str, *, quiet: bool = False) -> Path:
    """폰트가 없으면 Google Fonts 저장소에서 받는다."""
    target = font_path(key)
    if target.is_file():
        return target
    info = FONTS[key]
    url = f"{GOOGLE_FONTS_RAW}/{info.path}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(f"폰트 내려받는 중: {info.name}", file=sys.stderr)
    tmp = target.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1 << 16):
                out.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise SonError(
            f"폰트를 내려받지 못했습니다: {url}\n({exc})\n"
            f"직접 받아서 {target} 에 두어도 됩니다."
        ) from exc
    tmp.replace(target)
    return target


def ensure_font(key: str) -> Path:
    return download_font(key, quiet=False)


class _FlattenPen(BasePen):
    """곡선을 잘게 쪼개 윤곽선을 점 목록으로 모은다."""

    def __init__(self, glyphset, steps: int = 8):
        super().__init__(glyphset)
        self.steps = steps
        self.contours: list[list[tuple[float, float]]] = []
        self._current: list[tuple[float, float]] = []

    def _moveTo(self, pt):
        self._current = [pt]

    def _lineTo(self, pt):
        self._current.append(pt)

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        for i in range(1, self.steps + 1):
            t = i / self.steps
            mt = 1 - t
            x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
            y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
            self._current.append((x, y))

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        for i in range(1, self.steps + 1):
            t = i / self.steps
            mt = 1 - t
            x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
            y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
            self._current.append((x, y))

    def _closePath(self):
        if len(self._current) >= 3:
            self.contours.append(self._current)
        self._current = []

    _endPath = _closePath


@dataclass
class GlyphOutline:
    advance: float  # em 단위
    contours: list[np.ndarray]  # 각 (N, 2), em 단위, y 는 위쪽이 +


class HandFont:
    """폰트 하나. 글리프 윤곽선을 em 단위로 정규화해 돌려준다.

    폰트마다 글자 크기 느낌이 달라서, '가' 의 높이가 0.72em 이 되도록 맞춘다.
    그래서 같은 --size 면 어느 폰트든 비슷한 크기로 보인다.
    """

    REFERENCE_CHAR = "가"
    REFERENCE_HEIGHT = 0.72

    def __init__(self, key: str):
        self.key = key
        self.path = ensure_font(key)
        self._font = TTFont(self.path, lazy=True)
        self._cmap = self._font.getBestCmap()
        self._glyphset = self._font.getGlyphSet()
        self._hmtx = self._font["hmtx"]
        self.upm = self._font["head"].unitsPerEm
        self._cache: dict[str, GlyphOutline] = {}
        self.norm = 1.0
        ref = self._raw(self.REFERENCE_CHAR)
        if ref is not None and ref.contours:
            ys = np.concatenate([c[:, 1] for c in ref.contours])
            height = float(ys.max() - ys.min())
            if height > 0:
                self.norm = self.REFERENCE_HEIGHT / height

    def has(self, ch: str) -> bool:
        return ord(ch) in self._cmap

    def _raw(self, ch: str) -> GlyphOutline | None:
        name = self._cmap.get(ord(ch))
        if name is None:
            return None
        pen = _FlattenPen(self._glyphset)
        self._glyphset[name].draw(pen)
        scale = 1.0 / self.upm
        contours = [np.asarray(c, dtype=np.float64) * scale for c in pen.contours]
        advance = self._hmtx[name][0] * scale
        return GlyphOutline(advance, contours)

    def outline(self, ch: str) -> GlyphOutline | None:
        if ch in self._cache:
            return self._cache[ch]
        raw = self._raw(ch)
        if raw is not None:
            raw = GlyphOutline(raw.advance * self.norm, [c * self.norm for c in raw.contours])
            self._cache[ch] = raw
        return raw


@lru_cache(maxsize=None)
def load_font(key: str) -> HandFont:
    return HandFont(key)


class FontChain:
    """주 폰트에 없는 글자는 대체 폰트에서 찾는다."""

    def __init__(self, primary: str):
        self.primary = load_font(primary)
        self._fallback_keys = [k for k in FALLBACK_ORDER if k != primary]
        self.missing: set[str] = set()

    def lookup(self, ch: str) -> GlyphOutline | None:
        glyph = self.primary.outline(ch)
        if glyph is not None:
            return glyph
        for key in self._fallback_keys:
            try:
                font = load_font(key)
            except SonError:
                continue
            glyph = font.outline(ch)
            if glyph is not None:
                return glyph
        self.missing.add(ch)
        return None
