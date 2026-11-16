import io
import json
import urllib.error

import pytest

from sonhangul import compose as C
from sonhangul.compose import (
    LLMClient, Recipient, build_prompt, clean_message, compose, normalize_length, parse_messages,
)
from sonhangul.config import Settings
from sonhangul.errors import SonError


def _settings(tmp_path, key="nvapi-test"):
    return Settings(nvidia_api_key=key, cache_dir=tmp_path / "cache")


class FakeResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _reply(messages):
    content = json.dumps({"messages": messages}, ensure_ascii=False)
    return FakeResponse({"choices": [{"message": {"content": content}}]})


def _http_error(code, headers=None):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(b'{"detail":"x"}'))


def test_prompt_contains_recipient_details():
    r = Recipient("김하늘", "직원", ["올해 입사", "등산 좋아함"], request="수고했다는 말", length="1")
    prompt = build_prompt(r, 3)
    for part in ("김하늘", "직원", "올해 입사", "등산 좋아함", "수고했다는 말", "45자", "문구 개수: 3"):
        assert part in prompt


def test_length_aliases():
    assert normalize_length("두 줄") == "2"
    assert normalize_length("편지") == "letter"
    assert normalize_length(None) == "2"
    with pytest.raises(SonError):
        normalize_length("아주 길게")


def test_clean_message_strips_emoji_quotes_and_numbering():
    assert clean_message('1. "올해 고생 많았어요 \U0001F60A"', 45) == "올해 고생 많았어요"
    assert clean_message("加油 하세요", 45) is None  # 한자가 섞인 문구는 버린다
    assert clean_message("Thank you!", 45) is None  # 한글이 없으면 버린다
    assert clean_message("", 45) is None


def test_clean_message_trims_overlong_text_at_sentence_end():
    text = "첫 문장입니다. " + "아주 긴 둘째 문장이 이어집니다 " * 5 + "."
    assert clean_message(text, 20) == "첫 문장입니다."


def test_parse_messages_accepts_json_and_plain_lines():
    assert parse_messages('{"messages": ["하나예요.", "둘이에요."]}', 45) == ["하나예요.", "둘이에요."]
    assert parse_messages('설명입니다:\n```json\n["하나예요."]\n```', 45)[-1] == "하나예요."
    assert parse_messages("- 하나예요.\n- 둘이에요.", 45) == ["하나예요.", "둘이에요."]


def test_compose_calls_api_with_bearer_key_and_caches(tmp_path, monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return _reply(["올해 첫 산행은 어디로 가세요? 덕분에 팀이 든든했어요."])

    monkeypatch.setattr(C.urllib.request, "urlopen", fake_urlopen)
    settings = _settings(tmp_path)
    r = Recipient("김하늘", "직원", ["등산 좋아함"])
    out = compose(r, settings)
    assert out[0].source == "llm" and "산행" in out[0].text
    req = calls[0]
    assert req.full_url == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer nvapi-test"
    body = json.loads(req.data)
    assert body["model"] == settings.llm_model
    assert "등산 좋아함" in body["messages"][1]["content"]

    again = compose(Recipient("김하늘", "직원", ["등산 좋아함"]), settings)
    assert again[0].text == out[0].text
    assert len(calls) == 1, "같은 입력은 캐시에서 읽어야 한다"
    compose(Recipient("김하늘", "직원", ["등산 좋아함"]), settings, use_cache=False)
    assert len(calls) == 2


def test_compose_asks_again_until_enough_variants(tmp_path, monkeypatch):
    replies = iter([_reply(["하나예요."]), _reply(["하나예요.", "둘이에요."]), _reply(["셋이에요."])])
    monkeypatch.setattr(C.urllib.request, "urlopen", lambda req, timeout=None: next(replies))
    out = compose(Recipient("가"), _settings(tmp_path), variants=3)
    assert [m.text for m in out] == ["하나예요.", "둘이에요.", "셋이에요."]


def test_retry_on_429_then_success(tmp_path, monkeypatch):
    attempts = []
    waits = []

    def fake_urlopen(req, timeout=None):
        attempts.append(1)
        if len(attempts) < 3:
            raise _http_error(429)
        return _reply(["고맙습니다."])

    monkeypatch.setattr(C.urllib.request, "urlopen", fake_urlopen)
    client = LLMClient(_settings(tmp_path), sleep=waits.append)
    assert "고맙습니다" in client.chat("s", "u")
    assert len(attempts) == 3
    assert waits == [2.0, 4.0], "지수 백오프"


def test_auth_error_is_not_retried(tmp_path, monkeypatch):
    attempts = []

    def fake_urlopen(req, timeout=None):
        attempts.append(1)
        raise _http_error(401)

    monkeypatch.setattr(C.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SonError, match="401"):
        LLMClient(_settings(tmp_path), sleep=lambda s: None).chat("s", "u")
    assert len(attempts) == 1


def test_gives_up_after_retries(tmp_path, monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("연결 끊김")

    monkeypatch.setattr(C.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SonError, match="3번 시도"):
        LLMClient(_settings(tmp_path), max_retries=2, sleep=lambda s: None).chat("s", "u")


def test_no_key_falls_back_to_templates(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("키가 없으면 API 를 부르면 안 된다")

    monkeypatch.setattr(C.urllib.request, "urlopen", boom)
    out = compose(Recipient("김하늘", traits=["등산"]), _settings(tmp_path, key=None), variants=2)
    assert len(out) == 2 and all(m.source == "template" for m in out)
    assert "NVIDIA_API_KEY" in capsys.readouterr().err


def test_offline_is_deterministic_per_name(tmp_path):
    s = _settings(tmp_path)
    a = compose(Recipient("김하늘"), s, offline=True, seed=1)
    b = compose(Recipient("김하늘"), s, offline=True, seed=1)
    assert a[0].text == b[0].text and a[0].source == "template"


def test_unusable_model_output_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(C.urllib.request, "urlopen", lambda req, timeout=None: _reply(["Thank you!"]))
    with pytest.raises(SonError, match="쓸 만한 문구"):
        compose(Recipient("가"), _settings(tmp_path))
