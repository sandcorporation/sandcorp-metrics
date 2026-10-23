"""경로 마스킹: 식별자처럼 보이는 경로 조각을 `*`로 바꾼다.

초대 코드·토큰처럼 조각 자체가 비밀인 주소(`/join/<code>`)가 조회 경로로 남지 않게 한다.
사이트별 설정 없이 일반 규칙만 쓴다. 순수 함수라 DB를 건드리지 않는다.
"""

import re

MASK = "*"

# 바로 뒤 조각은 길이와 무관하게 가린다(소문자 비교).
SECRET_PREFIXES = frozenset({"join", "invite", "reset", "verify", "confirm"})

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HEX = re.compile(r"[0-9a-fA-F]{8,}")
_DIGITS = re.compile(r"[0-9]{6,}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,}")


def _is_slug(segment: str) -> bool:
    """하이픈으로 나뉜 조각 중 글자만 있는 단어가 둘 이상이면 사람이 읽는 slug로 본다."""
    return sum(1 for part in segment.split("-") if part.isalpha()) >= 2


def _is_identifier(segment: str) -> bool:
    if _UUID.fullmatch(segment) or _DIGITS.fullmatch(segment) or _HEX.fullmatch(segment):
        return True
    return bool(
        _TOKEN.fullmatch(segment) and any(c.isdigit() for c in segment) and not _is_slug(segment)
    )


def mask_path(path: str) -> str:
    """`/`로 나눈 조각 가운데 식별자처럼 보이는 것을 `*`로 바꾼다(길이는 자르지 않는다)."""
    segments = path.split("/")
    for i, segment in enumerate(segments):
        if not segment:
            continue
        after_secret = i > 0 and segments[i - 1].lower() in SECRET_PREFIXES
        if after_secret or _is_identifier(segment):
            segments[i] = MASK
    return "/".join(segments)
