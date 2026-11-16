"""환경 변수와 .env 읽기."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    """폰트와 캐시를 둘 곳. 소스 폴더에서 쓰면 그 안에, pip 로 설치해 쓰면 홈 폴더 아래에."""
    if (PROJECT_ROOT / "pyproject.toml").is_file():
        return PROJECT_ROOT
    return Path.home() / ".cache" / "son-hangul"

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# build.nvidia.com 카탈로그에서 무료로 부를 수 있는 모델. 한국어 문장이 무난한 쪽.
DEFAULT_LLM_MODEL = "meta/llama-3.3-70b-instruct"


def _load_dotenv(path: Path) -> None:
    """의존성 없이 .env 를 읽어 os.environ 에 채운다(이미 있는 값은 유지)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def load_env(explicit: Path | None = None) -> None:
    """지정한 파일, 현재 폴더, 프로젝트 루트의 .env 를 차례로 읽는다."""
    for candidate in (explicit, Path.cwd() / ".env", PROJECT_ROOT / ".env"):
        if candidate is not None:
            _load_dotenv(candidate)


@dataclass
class Settings:
    nvidia_api_key: str | None = None
    llm_model: str = DEFAULT_LLM_MODEL
    base_url: str = NVIDIA_BASE_URL
    cache_dir: Path = field(default_factory=lambda: _data_root() / ".cache" / "compose")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            nvidia_api_key=os.getenv("NVIDIA_API_KEY") or None,
            llm_model=os.getenv("SON_LLM_MODEL", DEFAULT_LLM_MODEL),
            base_url=os.getenv("SON_LLM_BASE_URL", NVIDIA_BASE_URL),
            cache_dir=Path(os.getenv("SON_CACHE_DIR") or _data_root() / ".cache" / "compose"),
        )


def font_dir() -> Path:
    return Path(os.getenv("SON_FONT_DIR") or _data_root() / "fonts" / "_downloads")
