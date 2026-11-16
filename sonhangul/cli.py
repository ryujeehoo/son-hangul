"""handwrite 명령."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Settings, load_env
from .errors import SonError
from .fonts import DEFAULT_FONT, FONTS, download_font, font_path
from .ink import DEFAULT_PEN, PENS, get_pen, parse_color
from .page import PAGE_SIZES_MM, PageOptions, letter, mm_to_px, page_pixels, render_page
from .paper import DEFAULT_PAPER, PAPERS
from .render import HandStyle, Paragraph


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _add_style_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("글씨")
    g.add_argument("--font", default=DEFAULT_FONT, choices=sorted(FONTS), help=f"손글씨 폰트 (기본 {DEFAULT_FONT})")
    g.add_argument("--pen", default=DEFAULT_PEN, choices=sorted(PENS), help=f"펜 (기본 {DEFAULT_PEN})")
    g.add_argument("--color", help="잉크 색. #1a2b3c 또는 26,43,60 (기본: 펜마다 다름)")
    g.add_argument("--size", type=float, help="글씨 크기(px). 용지를 고르면 대신 --size-mm 을 쓰는 편이 쉽다")
    g.add_argument("--size-mm", type=float, help="글씨 크기(mm). 용지(--page)와 같이 쓴다 (기본 6.5mm, A4 는 5.5mm)")
    g.add_argument("--line-height", type=float, default=1.6, help="줄 간격(글씨 크기의 배수, 기본 1.6)")
    g.add_argument("--messiness", type=float, default=1.0, help="흐트러짐 정도. 0 = 폰트 그대로, 1 = 기본, 2 = 많이")
    g.add_argument("--seed", type=int, help="같은 숫자면 같은 결과가 나온다")

    g = p.add_argument_group("종이와 크기")
    g.add_argument("--paper", choices=sorted(PAPERS), help=f"종이 (기본: 이미지는 {DEFAULT_PAPER}, PDF 는 blank)")
    g.add_argument("--page", choices=sorted(PAGE_SIZES_MM), help="인쇄 규격. 고르면 --width/--height 대신 이 크기를 쓴다")
    g.add_argument("--landscape", action="store_true", help="용지를 가로로")
    g.add_argument("--dpi", type=int, default=300, help="인쇄 해상도 (기본 300)")
    g.add_argument("--width", type=int, help="이미지 너비(px, 기본 1200)")
    g.add_argument("--height", type=int, help="이미지 높이(px). 안 주면 글 길이에 맞춘다")
    g.add_argument("--margin-mm", type=float, help="여백(mm). 용지와 같이 쓴다")
    g.add_argument("--valign", choices=("top", "center"), help="세로 위치 (기본: 카드는 center, A4 는 top)")
    g.add_argument("--no-fit", action="store_true", help="글이 넘쳐도 글씨를 줄이지 않는다")


def _style_and_options(args, *, for_pdf: bool) -> tuple[HandStyle, object, PageOptions]:
    pen = get_pen(args.pen, parse_color(args.color) if args.color else None)
    dpi = args.dpi
    margin = None
    if args.page:
        width, height = page_pixels(args.page, dpi, args.landscape)
        size_mm = args.size_mm or (5.5 if args.page in ("a4", "a5") else 6.5)
        size = args.size or mm_to_px(size_mm, dpi)
        valign = args.valign or ("top" if args.page in ("a4", "a5") else "center")
    else:
        width, height = args.width or 1200, args.height
        size = args.size or (mm_to_px(args.size_mm, dpi) if args.size_mm else 56.0)
        valign = args.valign or "top"
    if args.margin_mm is not None:
        m = mm_to_px(args.margin_mm, dpi)
        margin = (m, m, m, m)
    if size <= 4:
        raise SonError("글씨가 너무 작습니다. --size 또는 --size-mm 을 키우세요.")
    paper = args.paper or ("blank" if for_pdf else DEFAULT_PAPER)
    if for_pdf and paper == "transparent":
        paper = "blank"
    style = HandStyle(
        font=args.font, size=float(size), line_height=args.line_height,
        messiness=max(0.0, args.messiness), seed=args.seed,
    )
    options = PageOptions(
        width=width, height=height, margin=margin, paper=paper,
        valign=valign, fit=not args.no_fit, dpi=dpi,
    )
    return style, pen, options


def _report(page) -> None:
    if page.layout.missing:
        log("경고: 폰트에 없는 글자를 건너뛰었습니다: " + " ".join(sorted(page.layout.missing)))
    if page.shrunk:
        log(f"글이 넘쳐서 글씨를 {page.size:.0f}px 로 줄였습니다.")
    if page.layout.overflow:
        log("경고: 글이 종이에 다 들어가지 않아 일부가 잘렸습니다.")


def _save(page, out: Path, *, textures: bool) -> list[Path]:
    from .export import save_pdf, save_png, save_texture_set

    if out.suffix.lower() == ".pdf":
        return [save_pdf([page], out)]
    if textures:
        return save_texture_set(page, out)
    return [save_png(page, out)]


def cmd_render(args) -> int:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = " ".join(args.text)
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise SonError("쓸 글이 없습니다. 글을 인자로 주거나 -f 파일을 지정하세요.")
    text = text.replace("\\n", "\n").strip()
    if not text:
        raise SonError("쓸 글이 비어 있습니다.")
    out = Path(args.output)
    style, pen, options = _style_and_options(args, for_pdf=out.suffix.lower() == ".pdf")
    if args.transparent:
        options.paper = "transparent"
    if args.to or args.sender or args.date:
        content = letter(text, to=args.to, sender=args.sender, date=args.date)
    else:
        content = [Paragraph(text, align=args.align)]
    page = render_page(content, style, pen, options)
    _report(page)
    for path in _save(page, out, textures=args.textures):
        print(path)
    return 0


def _recipient_from_args(args):
    from .compose import Recipient, normalize_length

    traits = [t.strip() for t in (args.traits or "").replace(";", ",").split(",") if t.strip()]
    return Recipient(
        name=args.name, relation=args.relation or "", traits=traits, request=args.request or "",
        tone=args.tone, length=normalize_length(args.length), sender=args.sender or "",
    )


def cmd_compose(args) -> int:
    from .compose import compose

    settings = Settings.from_env()
    if args.model:
        settings.llm_model = args.model
    recipient = _recipient_from_args(args)
    messages = compose(
        recipient, settings, variants=args.variants, offline=args.offline,
        use_cache=not args.no_cache, seed=args.seed,
    )
    for i, m in enumerate(messages, start=1):
        tag = "" if m.source == "llm" else " (미리 적어 둔 문구)"
        print(f"{i}. {m.text}{tag}")
    if args.output:
        out = Path(args.output)
        style, pen, options = _style_and_options(args, for_pdf=out.suffix.lower() == ".pdf")
        pick = messages[min(max(args.pick, 1), len(messages)) - 1]
        to = args.greeting.format(name=recipient.name) if args.greeting else None
        page = render_page(letter(pick.text, to=to, sender=recipient.sender or None), style, pen, options)
        _report(page)
        for path in _save(page, out, textures=False):
            print(path)
    return 0


def cmd_batch(args) -> int:
    from .batch import compose_all, read_messages, read_recipients, render_cards, write_messages

    outdir = Path(args.output)
    style, pen, options = _style_and_options(args, for_pdf=args.format == "pdf")
    if not args.page and not args.height:
        raise SonError("카드 크기를 정해 주세요. 예: --page a6 (또는 --width 와 --height)")

    if args.messages:
        cards = read_messages(args.messages)
        log(f"{args.messages} 의 문구 {len(cards)}개로 카드를 만듭니다(문장 생성은 건너뜁니다).")
    else:
        if not args.recipients:
            raise SonError("받는 사람 명단(CSV)이나 --messages 파일이 필요합니다.")
        settings = Settings.from_env()
        if args.model:
            settings.llm_model = args.model
        recipients = read_recipients(args.recipients, default_sender=args.sender or "")
        log(f"{len(recipients)}명의 문구를 만듭니다.")
        cards = compose_all(
            recipients, settings, greeting=args.greeting, offline=args.offline,
            use_cache=not args.no_cache, seed=args.seed, jobs=max(1, args.jobs),
        )
        messages_path = write_messages(cards, outdir / "messages.csv")
        log(f"문구를 저장했습니다: {messages_path}")
        templated = sum(1 for c in cards if c.source == "template")
        if templated:
            log(f"주의: {templated}명은 미리 적어 둔 문구라 받는 사람 특징이 들어가지 않았습니다.")
        if args.compose_only:
            log("문구를 검토·수정한 뒤 --messages 로 다시 실행하면 카드를 만듭니다.")
            print(messages_path)
            return 0

    outputs = render_cards(cards, style, pen, options, outdir, fmt=args.format, combined=not args.no_combined)
    log(f"{len(cards)}장을 만들었습니다: {outdir}")
    print(outputs[-1])
    return 0


def cmd_fonts(args) -> int:
    for key, info in FONTS.items():
        have = "받음" if font_path(key).is_file() else "아직 안 받음"
        print(f"{key:12s} {info.name}  [{info.license}, {have}]\n{'':12s} {info.note}")
    if args.download:
        for key in FONTS:
            download_font(key)
        log("폰트를 모두 받았습니다.")
    return 0


def cmd_list(args) -> int:
    print("펜:")
    for key, pen in PENS.items():
        print(f"  {key:15s} {pen.name}")
    print("종이:")
    for key, paper in PAPERS.items():
        print(f"  {key:15s} {paper.name}")
    print("용지:")
    for key, (w, h) in PAGE_SIZES_MM.items():
        print(f"  {key:15s} {w:g} x {h:g} mm")
    return 0


def cmd_models(args) -> int:
    from .compose import list_models

    settings = Settings.from_env()
    chain = [settings.llm_model, *settings.llm_fallbacks]
    for name in list_models(settings):
        mark = f"  <- 지금 설정({chain.index(name) + 1}순위)" if name in chain else ""
        print(f"{name}{mark}")
    log("목록에 있어도 계정에 따라 못 쓰는 모델이 있습니다. 글쓰기용이 아닌 모델도 섞여 있습니다.")
    return 0


def cmd_web(args) -> int:
    from .webui import launch

    launch(host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handwrite",
        description="한글 문장을 사람이 쓴 것 같은 손글씨 이미지·PDF 로 만든다.",
    )
    parser.add_argument("--version", action="version", version=f"son-hangul {__version__}")
    parser.add_argument("--env", help=".env 파일 경로")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("render", help="글을 손글씨로 그린다")
    p.add_argument("text", nargs="*", help="쓸 글. 줄바꿈은 \\n")
    p.add_argument("-f", "--file", help="글이 든 텍스트 파일")
    p.add_argument("-o", "--output", default="handwriting.png", help="저장할 파일(.png 또는 .pdf)")
    p.add_argument("--align", choices=("left", "center", "right"), default="left")
    p.add_argument("--to", help="받는 사람 줄. 예: '민수 님께'")
    p.add_argument("--from", dest="sender", help="보내는 사람 줄(오른쪽 정렬). 예: '박서연 드림'")
    p.add_argument("--date", help="날짜 줄(오른쪽 정렬)")
    p.add_argument("--transparent", action="store_true", help="배경 없는 투명 PNG (게임 텍스처용)")
    p.add_argument("--textures", action="store_true", help="잉크만/노멀맵/러프니스맵도 함께 저장")
    _add_style_args(p)
    p.set_defaults(func=cmd_render)

    def add_compose_args(q: argparse.ArgumentParser) -> None:
        g = q.add_argument_group("문장 생성")
        g.add_argument("--model", help="NVIDIA NIM 모델 이름 (기본: SON_LLM_MODEL)")
        g.add_argument("--offline", action="store_true", help="API 없이 미리 적어 둔 문구에서 고른다")
        g.add_argument("--no-cache", action="store_true", help="같은 입력이어도 새로 만든다")

    p = sub.add_parser("compose", help="받는 사람에게 맞춘 문구를 만든다")
    p.add_argument("--name", required=True, help="받는 사람 이름")
    p.add_argument("--relation", help="관계. 예: 고객, 직원, 동료")
    p.add_argument("--traits", help="특징 한두 개(쉼표로 구분). 예: '올해 입사, 등산 좋아함'")
    p.add_argument("--request", help="꼭 담을 말이나 상황")
    p.add_argument("--tone", default="따뜻하고 담백하게", help="어조")
    p.add_argument("--length", default="2", help="1(한 줄) | 2(두 줄) | letter(짧은 편지)")
    p.add_argument("--from", dest="sender", help="보내는 사람")
    p.add_argument("--variants", type=int, default=3, help="문구를 몇 개 만들지 (기본 3)")
    p.add_argument("-o", "--output", help="주면 고른 문구를 손글씨로 저장한다(.png/.pdf)")
    p.add_argument("--pick", type=int, default=1, help="몇 번째 문구를 그릴지 (기본 1)")
    p.add_argument("--greeting", default="{name} 님께", help="받는 사람 줄. 빈 문자열이면 생략")
    add_compose_args(p)
    _add_style_args(p)
    p.set_defaults(func=cmd_compose)

    p = sub.add_parser("batch", help="명단(CSV)으로 카드를 한꺼번에 만든다")
    p.add_argument("recipients", nargs="?", help="받는 사람 명단 CSV (name, relation, traits, request, tone, length, sender)")
    p.add_argument("-o", "--output", default="out", help="결과 폴더 (기본 out)")
    p.add_argument("--format", choices=("pdf", "png"), default="pdf")
    p.add_argument("--messages", help="검토를 마친 messages.csv. 주면 문장 생성 없이 카드만 만든다")
    p.add_argument("--compose-only", action="store_true", help="문구만 만들어 messages.csv 로 저장하고 멈춘다")
    p.add_argument("--greeting", default="{name} 님께", help="받는 사람 줄")
    p.add_argument("--from", dest="sender", help="명단에 보내는 사람이 없을 때 쓸 이름")
    p.add_argument("--no-combined", action="store_true", help="all_cards.pdf 를 만들지 않는다")
    p.add_argument("--jobs", type=int, default=3, help="문구를 몇 명씩 동시에 만들지 (기본 3)")
    add_compose_args(p)
    _add_style_args(p)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("fonts", help="쓸 수 있는 손글씨 폰트")
    p.add_argument("--download", action="store_true", help="전부 미리 내려받는다")
    p.set_defaults(func=cmd_fonts)

    p = sub.add_parser("models", help="NVIDIA 카탈로그에서 지금 쓸 수 있는 모델 이름")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("list", help="펜, 종이, 용지 목록")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("web", help="브라우저에서 미리보기(Gradio 필요: pip install 'son-hangul[web]')")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7860)
    p.set_defaults(func=cmd_web)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_env(Path(args.env) if args.env else None)
    try:
        return args.func(args)
    except SonError as exc:
        log(f"오류: {exc}")
        return 1
    except KeyboardInterrupt:
        log("중단했습니다.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
