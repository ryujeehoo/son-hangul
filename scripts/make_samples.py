"""README 에 넣는 샘플을 다시 만든다: python scripts/make_samples.py

이름과 내용은 모두 지어낸 것이다. 실제 사람 정보를 넣지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from sonhangul.export import normal_map, save_pdf
from sonhangul.fonts import FONTS
from sonhangul.ink import PENS, get_pen
from sonhangul.page import PageOptions, letter, page_pixels, render_page
from sonhangul.render import HandStyle

OUT = Path(__file__).resolve().parent.parent / "docs" / "samples"


def stack(images: list[Image.Image], gap: int = 0, bg=(255, 255, 255)) -> Image.Image:
    w = max(i.width for i in images)
    h = sum(i.height for i in images) + gap * (len(images) - 1)
    sheet = Image.new("RGB", (w, h), bg)
    y = 0
    for im in images:
        sheet.paste(im.convert("RGB"), (0, y))
        y += im.height + gap
    return sheet


def side_by_side(images: list[Image.Image], gap: int = 0, bg=(255, 255, 255)) -> Image.Image:
    h = max(i.height for i in images)
    w = sum(i.width for i in images) + gap * (len(images) - 1)
    sheet = Image.new("RGB", (w, h), bg)
    x = 0
    for im in images:
        sheet.paste(im.convert("RGB"), (x, 0))
        x += im.width + gap
    return sheet


def save_jpg(image: Image.Image, name: str) -> None:
    image.convert("RGB").save(OUT / name, "JPEG", quality=88, optimize=True)
    print(OUT / name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. 대표 샘플: 카드 한 장
    body = "올해 입사하시고 벌써 한 해가 다 갔네요. 주말마다 산에 다니신다는 얘기 듣고 저도 등산화를 샀어요. 내년에는 같이 한번 올라가요."
    paras = letter(body, to="하늘 님께", sender="영업2팀 박서연 드림", date="2026. 11. 16.")
    w, h = page_pixels("a6", 150, landscape=True)
    card = render_page(paras, HandStyle(size=36, seed=21), get_pen("gel"),
                       PageOptions(width=w, height=h, paper="plain", valign="center", dpi=150))
    save_jpg(card.image, "card.jpg")

    # 인쇄용 PDF (흰 바탕, 300dpi)
    w, h = page_pixels("a6", 300, landscape=True)
    printable = render_page(paras, HandStyle(size=72, seed=21), get_pen("gel"),
                            PageOptions(width=w, height=h, paper="blank", valign="center"))
    print(save_pdf([printable], OUT / "card_print.pdf"))

    # 2. 같은 글자가 매번 다르게: 흐트러짐 0 / 1 / 1.8
    rows = []
    for m in (0.0, 1.0, 1.8):
        page = render_page(f"가가가가가 를를를를를 요요요요요  (흐트러짐 {m:g})", HandStyle(size=50, seed=4, messiness=m),
                           get_pen("gel"), PageOptions(width=1100, paper="blank"))
        rows.append(page.image)
    stack(rows).save(OUT / "messiness.png", optimize=True)
    print(OUT / "messiness.png")

    # 3. 폰트
    rows = []
    for key, info in FONTS.items():
        page = render_page(f"따뜻한 말 한마디가 오래 남아요. ({key})", HandStyle(font=key, size=42, seed=8),
                           get_pen("gel"), PageOptions(width=1000, paper="blank", margin=(22, 30, 14, 30)))
        rows.append(page.image)
    stack(rows).save(OUT / "fonts.png", optimize=True)
    print(OUT / "fonts.png")

    # 4. 펜
    rows = []
    for key, pen in PENS.items():
        page = render_page(f"{pen.name}으로 쓴 글씨예요. 2026년 겨울 ({key})", HandStyle(size=42, seed=5),
                           pen, PageOptions(width=1000, paper="plain", margin=(22, 30, 14, 30)))
        rows.append(page.image)
    save_jpg(stack(rows), "pens.jpg")

    # 5. 종이
    tiles = []
    for paper, pen, font in [("lined", "ballpoint-blue", "gaegu"), ("grid", "pencil", "hi-melody"),
                             ("kraft", "marker", "nanum-pen"), ("aged", "fountain", "nanum-pen")]:
        page = render_page(letter("늘 고맙습니다. 덕분에 한 해를 잘 보냈어요.", to="도윤 님께", sender="온새미 커피"),
                           HandStyle(font=font, size=34, seed=13), get_pen(pen),
                           PageOptions(width=560, height=400, paper=paper, valign="center"))
        tiles.append(page.image)
    save_jpg(stack([side_by_side(tiles[:2], 8), side_by_side(tiles[2:], 8)], 8), "papers.jpg")

    # 6. 게임 텍스처: 낡은 쪽지 / 투명 잉크를 다른 배경에 / 노멀맵
    note = "열쇠는 화분 밑에 뒀어.\n지하실 문은 절대 열지 마.\n- K"
    style = HandStyle(font="poor-story", size=40, seed=31, messiness=1.4)
    opts = dict(width=512, height=512, valign="center")
    aged = render_page(note, style, get_pen("fountain"), PageOptions(paper="aged", **opts))
    clear = render_page(note, style, get_pen("pencil", (235, 235, 225)), PageOptions(paper="transparent", **opts))
    wall = Image.new("RGB", (512, 512), (52, 70, 62))
    ImageDraw.Draw(wall).rectangle([0, 380, 512, 512], fill=(44, 60, 53))
    wall.paste(clear.image, mask=clear.image.getchannel("A"))
    save_jpg(side_by_side([aged.image, wall, normal_map(aged)], 8), "game_texture.jpg")


if __name__ == "__main__":
    main()
