"""명단 일괄 처리: recipients.csv → messages.csv(검토·수정) → 카드 이미지/PDF.

문장 생성과 렌더링을 나눠 둔다. messages.csv 를 사람이 고친 뒤 렌더링만 다시 돌릴 수 있다.
"""

from __future__ import annotations

import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .compose import Message, Recipient, compose, normalize_length
from .config import Settings
from .errors import SonError
from .export import save_pdf, save_png
from .ink import Pen
from .page import Page, PageOptions, letter, render_page
from .render import HandStyle

# CSV 머리글: 영어와 한글 둘 다 받는다.
_COLUMNS = {
    "name": ("name", "이름", "받는사람", "받는 사람"),
    "relation": ("relation", "관계"),
    "traits": ("traits", "특징"),
    "request": ("request", "요청", "요청사항"),
    "tone": ("tone", "어조", "말투"),
    "length": ("length", "길이"),
    "sender": ("sender", "보내는사람", "보내는 사람"),
    "message": ("message", "문구", "메시지"),
    "greeting": ("greeting", "호칭"),
    "source": ("source", "출처"),
}

MESSAGE_FIELDS = ["no", "name", "greeting", "message", "sender", "source"]


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SonError(f"파일이 없습니다: {path}")
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SonError(f"머리글이 없는 CSV 입니다: {path}")
        lookup = {}
        for field in reader.fieldnames:
            key = (field or "").strip().lower()
            for canonical, names in _COLUMNS.items():
                if key in names:
                    lookup[field] = canonical
        rows = []
        for raw in reader:
            row = {lookup[k]: (v or "").strip() for k, v in raw.items() if k in lookup}
            if any(row.values()):
                rows.append(row)
    return rows


def read_recipients(path: str | Path, *, default_sender: str = "") -> list[Recipient]:
    rows = _read_rows(Path(path))
    out: list[Recipient] = []
    for i, row in enumerate(rows, start=2):
        if not row.get("name"):
            raise SonError(f"{path} {i}번째 줄: 이름(name)이 비어 있습니다.")
        traits = [t.strip() for t in re.split(r"[,;/|·]", row.get("traits", "")) if t.strip()]
        out.append(
            Recipient(
                name=row["name"],
                relation=row.get("relation", ""),
                traits=traits,
                request=row.get("request", ""),
                tone=row.get("tone", "") or "따뜻하고 담백하게",
                length=normalize_length(row.get("length") or "2"),
                sender=row.get("sender", "") or default_sender,
            )
        )
    if not out:
        raise SonError(f"받는 사람이 한 명도 없습니다: {path}")
    return out


@dataclass
class CardText:
    no: int
    name: str
    greeting: str
    message: str
    sender: str
    source: str = ""


def compose_all(
    recipients: list[Recipient],
    settings: Settings,
    *,
    greeting: str = "{name} 님께",
    offline: bool = False,
    use_cache: bool = True,
    seed: int | None = None,
    jobs: int = 3,
) -> list[CardText]:
    """사람마다 문구를 하나씩 만든다. API 가 느려서 jobs 명씩 동시에 묻는다(순서는 명단 그대로)."""

    def one(item: tuple[int, Recipient]) -> CardText:
        i, r = item
        msg: Message = compose(r, settings, offline=offline, use_cache=use_cache, seed=seed)[0]
        print(f"  [{i}/{len(recipients)}] {r.name} 문구 완성", file=sys.stderr)
        return CardText(i, r.name, greeting.format(name=r.name), msg.text, r.sender, msg.source)

    items = list(enumerate(recipients, start=1))
    if offline or not settings.nvidia_api_key or jobs <= 1:
        return [one(item) for item in items]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, items))


def write_messages(cards: list[CardText], path: str | Path) -> Path:
    """엑셀에서 바로 열리도록 BOM 을 붙여 저장한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=MESSAGE_FIELDS)
        writer.writeheader()
        for c in cards:
            writer.writerow({k: getattr(c, k) for k in MESSAGE_FIELDS})
    return path


def read_messages(path: str | Path) -> list[CardText]:
    cards: list[CardText] = []
    for i, row in enumerate(_read_rows(Path(path)), start=1):
        if not row.get("message"):
            raise SonError(f"{path}: {row.get('name') or i}번 문구(message)가 비어 있습니다.")
        cards.append(
            CardText(i, row.get("name", ""), row.get("greeting", ""), row["message"],
                     row.get("sender", ""), row.get("source", ""))
        )
    if not cards:
        raise SonError(f"문구가 한 줄도 없습니다: {path}")
    return cards


def _safe_name(text: str) -> str:
    return re.sub(r"[^\w가-힣-]+", "_", text).strip("_") or "card"


def render_cards(
    cards: list[CardText],
    style: HandStyle,
    pen: Pen,
    options: PageOptions,
    outdir: str | Path,
    *,
    fmt: str = "pdf",
    combined: bool = True,
) -> list[Path]:
    """카드마다 시드를 달리해 한 장씩 그린다. 기울임은 같은 사람이 쓴 것처럼 고정한다."""
    if fmt not in ("pdf", "png"):
        raise SonError(f"형식은 pdf 또는 png 입니다: {fmt}")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    base_seed = style.seed if style.seed is not None else int(np.random.SeedSequence().entropy % (2**31))
    slant = style.slant
    if slant is None:
        slant = float(np.random.default_rng(base_seed).uniform(-0.03, 0.10)) * style.messiness

    outputs: list[Path] = []
    pages: list[Page] = []
    for card in cards:
        print(f"  [{card.no}/{len(cards)}] {card.name} 쓰는 중", file=sys.stderr)
        st = replace(style, seed=base_seed + card.no * 7919, slant=slant)
        page = render_page(
            letter(card.message, to=card.greeting or None, sender=card.sender or None), st, pen, options
        )
        if page.layout.overflow:
            print(f"    경고: {card.name} 카드는 글이 넘쳐 일부가 잘렸습니다. 문구를 줄이거나 용지를 키우세요.",
                  file=sys.stderr)
        stem = f"{card.no:03d}_{_safe_name(card.name)}"
        if fmt == "png":
            outputs.append(save_png(page, outdir / f"{stem}.png"))
        else:
            outputs.append(save_pdf([page], outdir / f"{stem}.pdf"))
            pages.append(page)
    if fmt == "pdf" and combined and pages:
        outputs.append(save_pdf(pages, outdir / "all_cards.pdf"))
    return outputs
