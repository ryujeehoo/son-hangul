import pytest

from sonhangul.errors import SonError
from sonhangul.fonts import DEFAULT_FONT, download_font


@pytest.fixture(scope="session")
def font():
    """기본 폰트가 있어야 하는 테스트용. 내려받을 수 없으면 건너뛴다."""
    try:
        download_font(DEFAULT_FONT, quiet=True)
    except SonError as exc:
        pytest.skip(f"폰트를 받을 수 없음: {exc}")
    return DEFAULT_FONT
