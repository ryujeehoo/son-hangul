"""손글씨 폰트 7종을 '서로 다른 사람 7명'으로 보고 자모 비율을 잰다.

    python scripts/analyze_fonts.py

결과 풀이는 docs/handwriting-analysis.md 에 있다.
"""

from __future__ import annotations

import numpy as np

from sonhangul.fonts import FONTS, load_font
from sonhangul.jamo import decompose, layout_of, segment

# KS X 1001 의 자주 쓰는 한글 2,350자
SYLLABLES = [bytes([a, b]).decode("euc-kr") for a in range(0xB0, 0xC9) for b in range(0xA1, 0xFF)]
COLUMNS = [
    ("cho_h", "초성높이"), ("ieung", "ㅇ크기"), ("vlen", "세로모음"), ("hlen", "가로모음"),
    ("jong_h", "받침높이"), ("jong_w", "받침너비"), ("aspect", "가로/세로"),
]


def box(contours, idx):
    pts = np.concatenate([contours[i] for i in idx])
    return pts.min(axis=0), pts.max(axis=0)


def measure(key: str) -> dict[str, float]:
    font = load_font(key)
    m: dict[str, list[float]] = {k: [] for k, _ in COLUMNS}
    done = seen = 0
    for ch in SYLLABLES:
        g = font.outline(ch)
        if g is None or not g.contours:
            continue
        seen += 1
        cho, jung, jong = decompose(ch)
        pts = np.concatenate(g.contours)
        gw, gh = pts.max(axis=0) - pts.min(axis=0)
        m["aspect"].append(gw / gh)
        seg = segment(ch, g.contours)
        if seg is None:
            continue
        done += 1
        (cl, ch_hi), (jl, jh) = box(g.contours, seg.cho), box(g.contours, seg.jung)
        lay = layout_of(jung)
        if lay == "v" and not jong:  # 가, 너, 이 ...
            m["cho_h"].append((ch_hi[1] - cl[1]) / gh)
            m["vlen"].append((jh[1] - jl[1]) / gh)
            if cho == "ㅇ":
                m["ieung"].append(((ch_hi[1] - cl[1]) + (ch_hi[0] - cl[0])) / 2 / gh)
        if lay == "h" and not jong:  # 고, 누, 므 ...: 모음 너비가 초성 너비의 몇 배인지
            m["hlen"].append((jh[0] - jl[0]) / max(ch_hi[0] - cl[0], 1e-6))
        if jong:
            tl, th = box(g.contours, seg.jong)
            m["jong_h"].append((th[1] - tl[1]) / gh)
            m["jong_w"].append((th[0] - tl[0]) / gw)
    out = {k: float(np.mean(v)) for k, v in m.items()}
    out["segmented"] = done / seen
    return out


def main() -> None:
    rows = {key: measure(key) for key in FONTS}
    print(f"{'폰트':12s}" + "".join(f"{name:>9s}" for _, name in COLUMNS) + f"{'나눈 비율':>9s}")
    for key, r in rows.items():
        print(f"{key:12s}" + "".join(f"{r[k]:9.2f}" for k, _ in COLUMNS) + f"{r['segmented']:9.0%}")
    print("\n사람 사이의 차이 (가장 큰 값 / 가장 작은 값)")
    for k, name in COLUMNS:
        v = [r[k] for r in rows.values()]
        print(f"  {name:8s} {min(v):.2f} ~ {max(v):.2f}   {max(v) / min(v):.2f}배")


if __name__ == "__main__":
    main()
