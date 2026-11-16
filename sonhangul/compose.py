"""받는 사람에게 맞춘 따뜻한 문장 만들기 (NVIDIA NIM, OpenAI 호환 API).

API 키가 없거나 --offline 이면 미리 적어 둔 문구에서 고른다. 그 문구에는 받는 사람의
특징이 들어가지 않으므로, 결과의 source 가 "template" 인지 확인하고 쓰는 쪽에서 알린다.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from .config import Settings
from .errors import SonError

# 길이 선택지: (설명, 최대 글자 수)
LENGTHS: dict[str, tuple[str, int]] = {
    "1": ("한 문장. 카드 한 줄에 들어갈 길이", 45),
    "2": ("두 문장. 카드 두세 줄에 들어갈 길이", 90),
    "letter": ("네다섯 문장의 짧은 편지", 240),
}
_LENGTH_ALIASES = {
    "1줄": "1", "한줄": "1", "한 줄": "1", "1line": "1", "one": "1",
    "2줄": "2", "두줄": "2", "두 줄": "2", "2line": "2", "two": "2",
    "편지": "letter", "짧은편지": "letter", "짧은 편지": "letter",
}


def normalize_length(value: str | None) -> str:
    v = (value or "2").strip().lower()
    v = _LENGTH_ALIASES.get(v, v)
    if v not in LENGTHS:
        raise SonError(f"길이는 1(한 줄), 2(두 줄), letter(짧은 편지) 중 하나입니다: {value}")
    return v


@dataclass
class Recipient:
    name: str
    relation: str = ""  # 고객, 직원, 동료 ...
    traits: list[str] = field(default_factory=list)  # "올해 입사", "등산 좋아함"
    request: str = ""  # 꼭 담을 말이나 상황
    tone: str = "따뜻하고 담백하게"
    length: str = "2"
    sender: str = ""  # 보내는 사람(문장 생성에 참고만 한다)


@dataclass
class Message:
    text: str
    source: str  # "llm" | "template"


SYSTEM_PROMPT = """너는 손편지 문구를 대신 써 주는 사람이다. 받는 사람 한 명에게 손으로 적어 줄 짧은 한국어 문장을 쓴다.

규칙:
- 받는 사람의 특징 가운데 적어도 하나를 자연스럽게 녹인다. 특징을 그대로 나열하지 말고, 그 사람을 지켜본 사람이 건네는 말처럼 쓴다.
- 사람이 펜으로 직접 쓸 법한 말투로 쓴다. 광고 문구, 과장된 칭찬, 격식만 차린 인사말은 쓰지 않는다.
- 어조에 반말로 쓰라는 말이 없으면 존댓말(해요체나 합니다체)로 쓴다. 문장은 마침표로 끝낸다.
- 받는 사람 이름을 문장 첫머리에서 부르지 않는다. 호칭 줄은 따로 적는다.
- 이모지, 이모티콘, 해시태그, 따옴표, 한자, 영어 문장은 쓰지 않는다.
- 주어지지 않은 사실(날짜, 숫자, 사건)을 지어내지 않는다. 특징에서 미루어 짐작한 일화("그때 ~해 주셨죠")도 만들지 않는다.
- "~님께" 같은 호칭 줄과 "~드림" 같은 맺음 줄은 쓰지 않는다. 본문만 쓴다.
- 길이 제한을 지킨다.
- 서로 다른 느낌의 문구를 요청한 개수만큼 쓴다.

출력은 JSON 하나만: {"messages": ["문구1", "문구2"]}"""


def build_prompt(r: Recipient, n: int) -> str:
    desc, limit = LENGTHS[normalize_length(r.length)]
    lines = [f"받는 사람: {r.name}"]
    if r.relation:
        lines.append(f"관계: {r.relation}")
    lines.append("특징: " + (", ".join(r.traits) if r.traits else "(알려진 것 없음. 일반적인 따뜻한 말로)"))
    if r.request:
        lines.append(f"요청사항: {r.request}")
    if r.sender:
        lines.append(f"보내는 사람: {r.sender}")
    lines.append(f"어조: {r.tone or '따뜻하고 담백하게'}")
    lines.append(f"길이: {desc} (공백 포함 {limit}자 이내)")
    lines.append(f"문구 개수: {n}")
    return "\n".join(lines)


# ── 응답 다듬기 ─────────────────────────────────────────────

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\U00002B00-\U00002BFF️‍]"
)
_FOREIGN = re.compile("[一-鿿぀-ヿ]")  # 한자, 가나: 모델이 가끔 섞는다
_HANGUL = re.compile("[가-힣]")


def clean_message(text: str, limit: int) -> str | None:
    """모델이 낸 문구 하나를 손글씨로 쓸 수 있게 다듬는다. 못 쓸 문구면 None."""
    t = _EMOJI.sub("", text)
    t = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", t)
    t = t.strip().strip("\"'“”‘’「」『』").strip()
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", " ", t)
    if not t or not _HANGUL.search(t) or _FOREIGN.search(t):
        return None
    if len(t) > limit * 1.25:
        # 너무 길면 문장 단위로 줄인다. 한 문장도 안 들어가면 버린다.
        kept = ""
        for sentence in re.findall(r"[^.!?~]+[.!?~]*\s*", t):
            if len(kept) + len(sentence.rstrip()) > limit * 1.25:
                break
            kept += sentence
        t = kept.strip()
        if not t:
            return None
    return t


def parse_messages(content: str, limit: int) -> list[str]:
    """JSON 을 기대하지만, 줄 목록으로 답해도 받아 준다."""
    candidates: list[str] = []
    match = re.search(r"\{.*\}", content, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            raw = data.get("messages") if isinstance(data, dict) else None
            if isinstance(raw, list):
                candidates = [str(x) for x in raw]
        except json.JSONDecodeError:
            pass
    if not candidates:
        match = re.search(r"\[.*\]", content, re.S)
        if match:
            try:
                raw = json.loads(match.group(0))
                if isinstance(raw, list):
                    candidates = [str(x) for x in raw]
            except json.JSONDecodeError:
                pass
    if not candidates and '"' in content and re.search(r"[{\[]", content):
        # JSON 이 깨져 있으면 따옴표로 묶인 문자열만 건진다.
        candidates = [
            m.group(1) for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', content) if m.group(1) != "messages"
        ]
    if not candidates:
        candidates = [ln for ln in content.splitlines() if ln.strip() and not ln.strip().startswith(("{", "}", "[", "]"))]
    out: list[str] = []
    for c in candidates:
        cleaned = clean_message(c, limit)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


# ── API 호출 ────────────────────────────────────────────────

RETRY_STATUS = {408, 429, 500, 502, 503, 504}
GONE_STATUS = {404, 410}  # 모델이 내려갔거나 이 계정에서 쓸 수 없음


class ModelUnavailable(SonError):
    """이 모델로는 답을 받을 수 없다. 다른 모델로 넘어가면 될 수 있다."""


@dataclass
class LLMClient:
    settings: Settings
    max_retries: int = 4
    timeout: float = 300.0  # 무료 API 는 대기열 때문에 몇 분씩 걸리기도 한다
    sleep: Callable[[float], None] = time.sleep  # 테스트에서 바꿔 끼운다

    def chat(
        self, system: str, user: str, *, temperature: float = 0.8, max_tokens: int = 2000,
        model: str | None = None,
    ) -> str:
        model = model or self.settings.llm_model
        if not self.settings.nvidia_api_key:
            raise SonError(
                "NVIDIA_API_KEY 가 없습니다.\n"
                "https://build.nvidia.com 에서 키를 받아 .env 에 NVIDIA_API_KEY=nvapi-... 로 넣으세요.\n"
                "키 없이 쓰려면 --offline 을 붙이세요(미리 적어 둔 문구에서 고릅니다)."
            )
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "top_p": 0.9,
            "max_tokens": max_tokens,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{self.settings.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.nvidia_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        last_error = ""
        for attempt in range(self.max_retries + 1):
            wait = 2.0 * (2**attempt)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                try:
                    content = data["choices"][0]["message"].get("content")
                except (KeyError, IndexError, TypeError, AttributeError) as exc:
                    raise SonError(f"LLM 응답 형식을 이해하지 못했습니다: {str(data)[:300]}") from exc
                if not content or not content.strip():
                    # 추론형 모델이 생각만 하다 토큰을 다 쓰면 답이 비어 온다.
                    raise ModelUnavailable(f"{model} 이(가) 답 없이 끝났습니다(생각하는 데 토큰을 다 씀).")
                return content.strip()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                last_error = f"LLM API 오류 {exc.code}: {detail}"
                if exc.code in GONE_STATUS:
                    raise ModelUnavailable(f"{model} 을(를) 쓸 수 없습니다({exc.code}): {detail[:200]}") from exc
                if exc.code not in RETRY_STATUS:
                    raise SonError(last_error) from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after and retry_after.isdigit():
                    wait = min(float(retry_after), 60.0)
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = f"LLM API 에 연결하지 못했습니다: {getattr(exc, 'reason', exc)}"
            if attempt < self.max_retries:
                print(f"  잠시 후 다시 시도합니다({wait:.0f}초): {last_error[:80]}", file=sys.stderr)
                self.sleep(wait)
        raise SonError(f"{self.max_retries + 1}번 시도했지만 실패했습니다. {last_error}")


# ── 오프라인 문구 ───────────────────────────────────────────

TEMPLATES: dict[str, list[str]] = {
    "1": [
        "늘 고맙습니다. 오늘도 좋은 하루 보내세요.",
        "덕분에 든든합니다. 항상 건강하세요.",
        "함께해 주셔서 고맙습니다.",
        "늘 응원하고 있어요. 좋은 일만 가득하길 바랍니다.",
        "잊지 않고 찾아 주셔서 감사합니다.",
    ],
    "2": [
        "늘 마음 써 주셔서 고맙습니다. 덕분에 한 해를 잘 보냈어요.",
        "함께할 수 있어서 든든했습니다. 앞으로도 잘 부탁드려요.",
        "바쁜 중에도 늘 챙겨 주셔서 감사합니다. 건강 잘 챙기세요.",
        "말로 다 못 한 고마움을 이렇게 적어 봅니다. 좋은 날 보내세요.",
        "생각날 때마다 고마운 분입니다. 늘 평안하시길 바랍니다.",
    ],
    "letter": [
        "그동안 고맙다는 말을 제대로 못 한 것 같아 이렇게 적습니다. 늘 한결같이 대해 주셔서 큰 힘이 되었어요. "
        "바쁘시더라도 끼니 거르지 마시고 건강 잘 챙기세요. 다음에 얼굴 보고 또 인사드리겠습니다.",
        "한 해 동안 함께해 주셔서 고맙습니다. 돌아보니 도움받은 일이 참 많았어요. "
        "새해에도 좋은 일만 있으시길 바랍니다. 늘 응원하겠습니다.",
    ],
}


def template_messages(r: Recipient, n: int, seed: int | None = None) -> list[Message]:
    pool = list(TEMPLATES[normalize_length(r.length)])
    rng = random.Random(f"{r.name}|{seed}")
    rng.shuffle(pool)
    return [Message(pool[i % len(pool)], "template") for i in range(n)]


# ── 묶어서 쓰는 함수 ────────────────────────────────────────


def list_models(settings: Settings, timeout: float = 30.0) -> list[str]:
    """카탈로그에 올라 있는 모델 이름들. 목록에 있어도 계정에 따라 못 쓰는 모델이 있다."""
    headers = {"Accept": "application/json"}
    if settings.nvidia_api_key:
        headers["Authorization"] = f"Bearer {settings.nvidia_api_key}"
    req = urllib.request.Request(f"{settings.base_url.rstrip('/')}/models", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return sorted(str(m["id"]) for m in data["data"])
    except (urllib.error.URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SonError(f"모델 목록을 받지 못했습니다: {exc}") from exc


def _cache_key(settings: Settings, system: str, user: str, n: int) -> str:
    blob = json.dumps([settings.base_url, settings.llm_model, system, user, n], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def compose(
    recipient: Recipient,
    settings: Settings,
    *,
    variants: int = 1,
    offline: bool = False,
    use_cache: bool = True,
    client: LLMClient | None = None,
    seed: int | None = None,
) -> list[Message]:
    """문구를 variants 개 만든다. 키가 없으면 오프라인 문구로 대신하고 경고한다."""
    recipient.length = normalize_length(recipient.length)
    variants = max(1, variants)
    if offline:
        return template_messages(recipient, variants, seed)
    if not settings.nvidia_api_key and client is None:
        print(
            "NVIDIA_API_KEY 가 없어 미리 적어 둔 문구를 씁니다(받는 사람 특징은 들어가지 않습니다).",
            file=sys.stderr,
        )
        return template_messages(recipient, variants, seed)

    _, limit = LENGTHS[recipient.length]
    user = build_prompt(recipient, variants)
    cache_file = settings.cache_dir / f"{_cache_key(settings, SYSTEM_PROMPT, user, variants)}.json"
    if use_cache and cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, list) and len(cached) >= variants:
                return [Message(str(t), "llm") for t in cached[:variants]]
        except (json.JSONDecodeError, OSError):
            pass

    client = client or LLMClient(settings)
    found: list[str] = []
    problems: list[str] = []
    models = list(dict.fromkeys([settings.llm_model, *settings.llm_fallbacks]))
    for model in models:
        try:
            # 모델이 개수를 덜 채우거나 못 쓸 문구를 낼 수 있어 두 번까지 더 묻는다.
            for _ in range(3):
                content = client.chat(
                    SYSTEM_PROMPT, user, model=model, max_tokens=1500 + limit * 4 * variants
                )
                for text in parse_messages(content, limit):
                    if text not in found:
                        found.append(text)
                if len(found) >= variants:
                    break
        except ModelUnavailable as exc:
            problems.append(str(exc))
            print(f"  {exc} 다음 모델로 넘어갑니다.", file=sys.stderr)
            continue
        if found:
            break
    if not found:
        if problems and len(problems) == len(models):
            raise SonError(
                "쓸 수 있는 모델이 없습니다.\n  " + "\n  ".join(problems)
                + "\n`handwrite models` 로 지금 쓸 수 있는 모델을 보고 .env 의 SON_LLM_MODEL 을 바꾸세요."
            )
        raise SonError("모델이 쓸 만한 문구를 내지 못했습니다. 모델을 바꾸거나(SON_LLM_MODEL) 다시 시도해 보세요.")
    found = found[:variants]
    if use_cache:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return [Message(t, "llm") for t in found]
