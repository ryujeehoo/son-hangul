import csv

import pytest

from sonhangul import cli
from sonhangul.batch import CardText, read_messages, read_recipients, write_messages
from sonhangul.config import _load_dotenv
from sonhangul.errors import SonError


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_read_recipients_english_and_korean_headers(tmp_path):
    en = _write(tmp_path / "en.csv", 'name,relation,traits,length\n김하늘,직원,"올해 입사, 등산",1\n')
    ko = _write(tmp_path / "ko.csv", "﻿이름,관계,특징,길이,보내는사람\n이도윤,고객,5년 단골/원두는 케냐,두 줄,온새미\n\n")
    a = read_recipients(en)[0]
    assert (a.name, a.relation, a.traits, a.length) == ("김하늘", "직원", ["올해 입사", "등산"], "1")
    b = read_recipients(ko, default_sender="기본")[0]
    assert (b.name, b.traits, b.length, b.sender) == ("이도윤", ["5년 단골", "원두는 케냐"], "2", "온새미")


def test_read_recipients_rejects_missing_name(tmp_path):
    with pytest.raises(SonError, match="이름"):
        read_recipients(_write(tmp_path / "x.csv", "name,traits\n,등산\n"))
    with pytest.raises(SonError, match="한 명도"):
        read_recipients(_write(tmp_path / "y.csv", "name,traits\n"))


def test_messages_roundtrip(tmp_path):
    cards = [CardText(1, "김하늘", "김하늘 님께", "고마워요, \"정말로\".", "서연", "llm")]
    path = write_messages(cards, tmp_path / "out" / "messages.csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf"), "엑셀용 BOM"
    back = read_messages(path)
    assert back == cards


def test_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env = _write(tmp_path / ".env", "# 주석\nSON_T1=파일값\nSON_T2='따옴표'\n")
    monkeypatch.setenv("SON_T1", "이미있음")
    monkeypatch.delenv("SON_T2", raising=False)
    _load_dotenv(env)
    import os

    assert os.environ["SON_T1"] == "이미있음"
    assert os.environ["SON_T2"] == "따옴표"


def test_cli_render_png_and_pdf(font, tmp_path, capsys):
    png = tmp_path / "a.png"
    assert cli.main(["render", "안녕하세요\\n반가워요", "--seed", "1", "--width", "500", "-o", str(png)]) == 0
    assert png.is_file() and str(png) in capsys.readouterr().out
    pdf = tmp_path / "a.pdf"
    assert cli.main(["render", "카드", "--page", "a6", "--dpi", "100", "--to", "민수 님께", "--from", "서연",
                     "--seed", "1", "-o", str(pdf)]) == 0
    assert pdf.read_bytes().startswith(b"%PDF")


def test_cli_render_without_text_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli.main(["render", "-o", str(tmp_path / "x.png")]) == 1
    assert "오류" in capsys.readouterr().err


def test_cli_batch_two_step_flow(font, tmp_path, monkeypatch, capsys):
    """문구만 만들기 → 사람이 고침 → 고친 문구로 카드 만들기."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    people = _write(tmp_path / "people.csv", "name,traits,sender\n김하늘,등산,서연\n이도윤,단골,서연\n")
    out = tmp_path / "out"
    common = ["--page", "a6", "--dpi", "72", "--seed", "3"]
    assert cli.main(["batch", str(people), "--offline", "--compose-only", "-o", str(out), *common]) == 0
    messages = out / "messages.csv"
    assert messages.is_file() and not list(out.glob("*.pdf"))

    rows = list(csv.DictReader(open(messages, encoding="utf-8-sig")))
    assert [r["name"] for r in rows] == ["김하늘", "이도윤"] and rows[0]["source"] == "template"
    rows[0]["message"] = "직접 고친 문구예요."
    with open(messages, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    assert cli.main(["batch", "--messages", str(messages), "-o", str(out), *common]) == 0
    names = sorted(p.name for p in out.glob("*.pdf"))
    assert names == ["001_김하늘.pdf", "002_이도윤.pdf", "all_cards.pdf"]
    assert read_messages(messages)[0].message == "직접 고친 문구예요."


def test_cli_batch_needs_card_size(tmp_path, capsys):
    people = _write(tmp_path / "p.csv", "name\n가\n")
    assert cli.main(["batch", str(people), "--offline", "-o", str(tmp_path / "o")]) == 1
    assert "카드 크기" in capsys.readouterr().err


def test_compose_all_keeps_order_when_parallel(tmp_path, monkeypatch):
    import time

    from sonhangul import batch as B
    from sonhangul.compose import Message, Recipient
    from sonhangul.config import Settings

    def slow_compose(r, settings, **kw):
        time.sleep(0.05 if r.name == "첫째" else 0.0)  # 첫 사람이 가장 늦게 끝나도 순서는 그대로
        return [Message(f"{r.name}에게", "llm")]

    monkeypatch.setattr(B, "compose", slow_compose)
    people = [Recipient("첫째"), Recipient("둘째"), Recipient("셋째")]
    cards = B.compose_all(people, Settings(nvidia_api_key="nvapi-x", cache_dir=tmp_path), jobs=3)
    assert [(c.no, c.name, c.message) for c in cards] == [(1, "첫째", "첫째에게"), (2, "둘째", "둘째에게"), (3, "셋째", "셋째에게")]
