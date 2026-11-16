"""브라우저 미리보기(Gradio). `handwrite web` 으로 띄운다."""

from __future__ import annotations

import tempfile
from pathlib import Path

from .compose import Recipient, compose
from .config import Settings, load_env
from .errors import SonError
from .export import save_pdf, save_png
from .fonts import DEFAULT_FONT, FONTS
from .ink import DEFAULT_PEN, PENS, get_pen
from .page import PAGE_SIZES_MM, PageOptions, letter, mm_to_px, page_pixels, render_page
from .paper import DEFAULT_PAPER, PAPERS
from .render import HandStyle

FREE_SIZE = "자유(글 길이에 맞춤)"


def make_page(text, to, sender, font, pen, paper, page_name, size_mm, messiness, seed, dpi=200):
    """화면에서 고른 값으로 한 장을 그린다. UI 없이도 부를 수 있게 따로 둔다."""
    text = (text or "").strip()
    if not text:
        raise SonError("쓸 글을 입력하세요.")
    size = float(mm_to_px(float(size_mm), dpi))
    if page_name and page_name != FREE_SIZE:
        width, height = page_pixels(page_name, dpi)
        valign = "top" if page_name in ("a4", "a5") else "center"
    else:
        width, height, valign = mm_to_px(150, dpi), None, "top"
    style = HandStyle(font=font, size=size, messiness=float(messiness), seed=int(seed))
    options = PageOptions(width=width, height=height, paper=paper, valign=valign, dpi=dpi)
    content = letter(text, to=(to or "").strip() or None, sender=(sender or "").strip() or None)
    return render_page(content, style, get_pen(pen), options)


def suggest(name, relation, traits, request, tone, length, sender):
    """문구 후보 세 개를 만든다. 키가 없으면 미리 적어 둔 문구가 나온다."""
    if not (name or "").strip():
        raise SonError("받는 사람 이름을 입력하세요.")
    recipient = Recipient(
        name=name.strip(), relation=relation or "",
        traits=[t.strip() for t in (traits or "").split(",") if t.strip()],
        request=request or "", tone=tone or "따뜻하고 담백하게", length=length, sender=sender or "",
    )
    return compose(recipient, Settings.from_env(), variants=3)


def build():
    import gradio as gr

    def on_render(*values):
        try:
            page = make_page(*values)
        except SonError as exc:
            raise gr.Error(str(exc)) from exc
        tmp = Path(tempfile.mkdtemp(prefix="sonhangul_"))
        png = save_png(page, tmp / "handwriting.png")
        pdf = save_pdf([page], tmp / "handwriting.pdf")
        note = []
        if page.shrunk:
            note.append(f"글이 넘쳐서 글씨를 줄였습니다({page.size / page.dpi * 25.4:.1f}mm).")
        if page.layout.overflow:
            note.append("글이 종이에 다 들어가지 않았습니다.")
        if page.layout.missing:
            note.append("폰트에 없는 글자: " + " ".join(sorted(page.layout.missing)))
        return page.image, [str(png), str(pdf)], " ".join(note)

    def on_suggest(*values):
        try:
            messages = suggest(*values)
        except SonError as exc:
            raise gr.Error(str(exc)) from exc
        label = "AI가 쓴 문구" if messages[0].source == "llm" else "미리 적어 둔 문구(API 키 없음: 받는 사람 특징이 들어가지 않습니다)"
        return gr.update(choices=[m.text for m in messages], value=messages[0].text, label=label), messages[0].text

    with gr.Blocks(title="son-hangul 손글씨") as demo:
        gr.Markdown("# son-hangul\n글을 넣으면 사람이 쓴 것 같은 손글씨로 그려 줍니다.")
        with gr.Row():
            with gr.Column(scale=1):
                with gr.Accordion("받는 사람에 맞춘 문구 만들기", open=False):
                    name = gr.Textbox(label="받는 사람 이름")
                    relation = gr.Textbox(label="관계", placeholder="고객, 직원, 동료 ...")
                    traits = gr.Textbox(label="특징(쉼표로 구분)", placeholder="올해 입사, 등산 좋아함")
                    request = gr.Textbox(label="요청사항", placeholder="한 해 수고했다는 말")
                    tone = gr.Textbox(label="어조", value="따뜻하고 담백하게")
                    length = gr.Radio([("한 줄", "1"), ("두 줄", "2"), ("짧은 편지", "letter")], value="2", label="길이")
                    suggest_btn = gr.Button("문구 만들기")
                    picks = gr.Radio([], label="문구 후보")
                text = gr.Textbox(label="쓸 글", lines=5, value="오늘도 수고 많으셨어요.\n내일 봬요!")
                to = gr.Textbox(label="받는 사람 줄(선택)", placeholder="민수 님께")
                sender = gr.Textbox(label="보내는 사람 줄(선택)", placeholder="서연 드림")
                font = gr.Dropdown([(i.name, k) for k, i in FONTS.items()], value=DEFAULT_FONT, label="글씨체")
                pen = gr.Dropdown([(p.name, k) for k, p in PENS.items()], value=DEFAULT_PEN, label="펜")
                paper = gr.Dropdown([(p.name, k) for k, p in PAPERS.items()], value=DEFAULT_PAPER, label="종이")
                page_name = gr.Dropdown([FREE_SIZE, *PAGE_SIZES_MM], value="a6", label="용지")
                size_mm = gr.Slider(3, 12, value=6.5, step=0.5, label="글씨 크기(mm)")
                messiness = gr.Slider(0, 2, value=1.0, step=0.1, label="흐트러짐(0 = 폰트 그대로)")
                seed = gr.Number(value=1, precision=0, label="시드(바꾸면 다시 쓴 것처럼 달라짐)")
                render_btn = gr.Button("손글씨로 쓰기", variant="primary")
            with gr.Column(scale=2):
                image = gr.Image(label="미리보기", type="pil")
                files = gr.Files(label="내려받기(PNG, PDF)")
                note = gr.Markdown()

        inputs = [text, to, sender, font, pen, paper, page_name, size_mm, messiness, seed]
        render_btn.click(on_render, inputs, [image, files, note])
        suggest_btn.click(on_suggest, [name, relation, traits, request, tone, length, sender], [picks, text])
        picks.change(lambda v: v or gr.skip(), picks, text)
    return demo


def launch(host: str = "127.0.0.1", port: int = 7860) -> None:
    try:
        import gradio  # noqa: F401
    except ImportError as exc:
        raise SonError("웹 화면에는 Gradio 가 필요합니다: pip install 'son-hangul[web]'") from exc
    load_env()
    build().launch(server_name=host, server_port=port)
