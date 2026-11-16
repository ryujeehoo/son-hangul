"""결과물 내보내기: PNG, 게임용 노멀맵·러프니스맵, 인쇄용 PDF."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .page import Page


def save_png(page: Page, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.image.save(path, dpi=(page.dpi, page.dpi))
    return path


def ink_only(page: Page) -> Image.Image:
    """종이 없이 잉크만 남긴 투명 배경 이미지."""
    h, w = page.alpha.shape
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., :3] = page.color
    out[..., 3] = np.uint8(np.clip(page.alpha, 0, 1) * 255 + 0.5)
    return Image.fromarray(out, "RGBA")


def normal_map(page: Page, strength: float = 2.0) -> Image.Image:
    """펜이 종이를 눌러 생긴 홈을 노멀맵(탄젠트 공간, OpenGL 식 +Y)으로."""
    a = Image.fromarray(np.uint8(np.clip(page.alpha, 0, 1) * 255 + 0.5))
    height = -np.asarray(a.filter(ImageFilter.GaussianBlur(max(0.8, page.size * 0.02))), dtype=np.float32) / 255.0
    dy, dx = np.gradient(height)
    nx, ny, nz = -dx * strength, dy * strength, np.ones_like(height)
    norm = np.sqrt(nx**2 + ny**2 + nz**2)
    rgb = np.stack([nx / norm, ny / norm, nz / norm], axis=-1) * 0.5 + 0.5
    return Image.fromarray(np.uint8(rgb * 255 + 0.5), "RGB")


def roughness_map(page: Page, paper: float = 0.92, ink: float = 0.45) -> Image.Image:
    """종이는 거칠고 잉크가 묻은 곳은 조금 매끈한 러프니스맵(흰색 = 거칢)."""
    r = paper + (ink - paper) * np.clip(page.alpha, 0, 1)
    return Image.fromarray(np.uint8(r * 255 + 0.5), "L")


def save_texture_set(page: Page, path: str | Path) -> list[Path]:
    """name.png 옆에 name_ink.png, name_normal.png, name_roughness.png 를 만든다."""
    path = Path(path)
    stem = path.with_suffix("")
    outputs = [save_png(page, path)]
    for suffix, image in (
        ("_ink", ink_only(page)),
        ("_normal", normal_map(page)),
        ("_roughness", roughness_map(page)),
    ):
        target = stem.parent / f"{stem.name}{suffix}.png"
        image.save(target)
        outputs.append(target)
    return outputs


def save_pdf(pages: list[Page], path: str | Path, *, jpeg_quality: int = 92) -> Path:
    """페이지마다 이미지 크기와 dpi 에 맞는 실제 치수로 PDF 를 만든다.

    흰 바탕은 무손실로, 종이 질감이 있으면 용량 때문에 JPEG 로 넣는다.
    """
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    pdf.setTitle(path.stem)
    for page in pages:
        image = page.image
        if image.mode == "RGBA":
            white = Image.new("RGB", image.size, (255, 255, 255))
            white.paste(image, mask=image.getchannel("A"))
            image = white
        w_pt = image.width / page.dpi * 72.0
        h_pt = image.height / page.dpi * 72.0
        pdf.setPageSize((w_pt, h_pt))
        colors = image.resize((64, 64)).getcolors(64 * 64) or []
        textured = len(colors) > 40
        if textured:
            buf = io.BytesIO()
            image.save(buf, "JPEG", quality=jpeg_quality, subsampling=0)
            buf.seek(0)
            pdf.drawImage(ImageReader(buf), 0, 0, w_pt, h_pt)
        else:
            pdf.drawImage(ImageReader(image), 0, 0, w_pt, h_pt)
        pdf.showPage()
    pdf.save()
    return path
