"""한글 음절을 초성·중성·종성 덩어리로 나누기.

폰트 글리프는 윤곽선 묶음일 뿐 어느 획이 어느 자모인지 적혀 있지 않다. 그래서 글리프를
작게 그려 서로 떨어진 덩어리를 찾고, 음절의 짜임(모음이 옆에 붙는지 아래에 붙는지,
받침이 있는지)에 따라 각 덩어리가 놓일 자리와 견주어 초성/중성/종성으로 가른다.
획이 서로 붙어 한 덩어리가 된 글자는 가를 수 없으므로 None 을 돌려준다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ",
        "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]

VERTICAL = set("ㅏㅐㅑㅒㅓㅔㅕㅖㅣ")  # 초성 오른쪽에 서는 모음
HORIZONTAL = set("ㅗㅛㅜㅠㅡ")  # 초성 아래에 눕는 모음
# 나머지(ㅘㅙㅚㅝㅞㅟㅢ)는 아래와 오른쪽을 함께 감싼다.


def decompose(ch: str) -> tuple[str, str, str] | None:
    """'한' → ('ㅎ', 'ㅏ', 'ㄴ'). 완성형 한글이 아니면 None."""
    code = ord(ch) - 0xAC00
    if not 0 <= code < 11172:
        return None
    return CHO[code // 588], JUNG[(code % 588) // 28], JONG[code % 28]


def layout_of(jung: str) -> str:
    if jung in VERTICAL:
        return "v"
    if jung in HORIZONTAL:
        return "h"
    return "m"


@dataclass
class Segments:
    """윤곽선 번호를 자모별로 나눈 결과."""

    cho: list[int]
    jung: list[int]
    jong: list[int]


def _label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """붙어 있는 픽셀끼리 같은 번호를 매긴다(8방향)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    count = 0
    filled = mask.tolist()
    for sy in range(h):
        row = filled[sy]
        for sx in range(w):
            if not row[sx] or labels[sy, sx]:
                continue
            count += 1
            stack = [(sy, sx)]
            labels[sy, sx] = count
            while stack:
                y, x = stack.pop()
                for ny in (y - 1, y, y + 1):
                    if not 0 <= ny < h:
                        continue
                    frow = filled[ny]
                    for nx in (x - 1, x, x + 1):
                        if 0 <= nx < w and frow[nx] and not labels[ny, nx]:
                            labels[ny, nx] = count
                            stack.append((ny, nx))
    return labels, count


# 짜임별로 각 자모가 놓이는 자리(글자 상자 안에서 0..1, y 는 위가 1).
# 중성이 두 군데로 갈리는 모음(ㅘ 등)은 자리를 둘 준다.
_ANCHORS: dict[tuple[str, bool], dict[str, list[tuple[float, float]]]] = {
    ("v", False): {"cho": [(0.28, 0.55)], "jung": [(0.82, 0.5)]},
    ("v", True): {"cho": [(0.28, 0.75)], "jung": [(0.82, 0.68)], "jong": [(0.5, 0.15)]},
    ("h", False): {"cho": [(0.5, 0.78)], "jung": [(0.5, 0.2)]},
    ("h", True): {"cho": [(0.5, 0.86)], "jung": [(0.5, 0.52)], "jong": [(0.5, 0.14)]},
    ("m", False): {"cho": [(0.35, 0.8)], "jung": [(0.4, 0.3), (0.85, 0.5)]},
    ("m", True): {"cho": [(0.35, 0.86)], "jung": [(0.4, 0.55), (0.85, 0.68)], "jong": [(0.5, 0.14)]},
}


def segment(ch: str, contours: list[np.ndarray], res: int = 96) -> Segments | None:
    """글리프 윤곽선을 초성·중성·종성으로 나눈다. 나눌 수 없으면 None."""
    parts = decompose(ch)
    if parts is None or not contours:
        return None
    _, jung, jong = parts
    has_jong = bool(jong)

    pts = np.concatenate(contours)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    bw, bh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    scale = (res - 4) / max(bw, bh)

    def to_px(c: np.ndarray) -> np.ndarray:
        return np.stack([(c[:, 0] - x0) * scale + 2, (y1 - c[:, 1]) * scale + 2], axis=1)

    winding = np.zeros((res, res), dtype=np.int16)
    for c in contours:
        q = to_px(c)
        area = 0.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], -1) - np.roll(q[:, 0], -1) * q[:, 1]))
        if area == 0:
            continue
        img = Image.new("1", (res, res), 0)
        ImageDraw.Draw(img).polygon([tuple(p) for p in q], fill=1)
        winding += np.asarray(img, dtype=np.int16) * (1 if area > 0 else -1)
    labels, count = _label(winding != 0)
    needed = 3 if has_jong else 2
    if count < needed:
        return None  # 획이 붙어서 덩어리 수가 모자람

    # 덩어리마다 무게중심(글자 상자 기준 0..1, y 는 위가 1)과 넓이
    comps = []
    total = 0
    for k in range(1, count + 1):
        ys, xs = np.nonzero(labels == k)
        cx = ((xs.mean() - 2) / scale) / bw
        cy = 1.0 - ((ys.mean() - 2) / scale) / bh
        comps.append((cx, cy, len(xs)))
        total += len(xs)

    anchors = _ANCHORS[(layout_of(jung), has_jong)]
    comp_role: list[str] = []
    for cx, cy, _ in comps:
        best, best_d = "cho", 1e9
        for role, spots in anchors.items():
            for ax, ay in spots:
                d = (cx - ax) ** 2 + (cy - ay) ** 2
                if d < best_d:
                    best, best_d = role, d
        comp_role.append(best)

    # 자모마다 덩어리가 하나는 있어야 하고, 부스러기만 받은 자모가 있으면 잘못 가른 것이다.
    share = {role: 0 for role in anchors}
    for role, (_, _, n) in zip(comp_role, comps):
        share[role] += n
    if any(share[role] < 0.07 * total for role in anchors):
        return None

    # 윤곽선마다 자기가 둘러싼 덩어리 번호를 찾는다(꼭짓점 둘레의 픽셀에서 다수결).
    out = Segments([], [], [])
    for i, c in enumerate(contours):
        q = np.clip(np.round(to_px(c)).astype(int), 1, res - 2)
        votes: dict[int, int] = {}
        for x, y in q[:: max(1, len(q) // 24)]:
            window = labels[y - 1 : y + 2, x - 1 : x + 2].ravel()
            for v in window[window > 0]:
                votes[int(v)] = votes.get(int(v), 0) + 1
        if not votes:
            return None
        role = comp_role[max(votes, key=votes.get) - 1]
        getattr(out, role).append(i)
    return out
