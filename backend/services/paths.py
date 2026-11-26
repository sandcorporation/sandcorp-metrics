"""경로 마스킹: 식별자처럼 보이는 경로 조각을 `*`로 바꾼다.

초대 코드·토큰처럼 조각 자체가 비밀인 주소(`/join/<code>`)가 조회 경로로 남지 않게 한다.
사이트별 설정 없이 일반 규칙만 쓴다. 순수 함수라 DB를 건드리지 않는다.
"""

import re
from datetime import date

MASK = "*"

# 바로 뒤 조각은 길이와 무관하게 가린다(소문자 비교).
SECRET_PREFIXES = frozenset({"join", "invite", "reset", "verify", "confirm"})

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HEX = re.compile(r"[0-9a-fA-F]{8,}")
_DIGITS = re.compile(r"[0-9]{6,}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,}")
_TWO_DIGITS = re.compile(r"[0-9]{2}")


def _is_word(part: str) -> bool:
    """글자만 있는 단어. 16진수 식별자처럼 보이는 것(`deadbeef`)은 단어가 아니다."""
    return part.isalpha() and not _HEX.fullmatch(part)


def _valid_date(year: str, month: str, day: str | None) -> bool:
    if not (1970 <= int(year) <= 2099 and 1 <= int(month) <= 12):
        return False
    if day is None:
        return True
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        return False
    return True


def _date_len(parts: list[str], i: int) -> int:
    """`parts[i]`에서 시작하는 날짜(`YYYYMMDD`·`YYYY-MM-DD`·`YYYY-MM`)의 조각 수, 아니면 0."""
    part = parts[i]
    if len(part) == 8 and part.isascii() and part.isdigit():
        return 1 if _valid_date(part[:4], part[4:6], part[6:]) else 0
    if not (len(part) == 4 and part.isascii() and part.isdigit()):
        return 0
    if i + 1 >= len(parts) or not _TWO_DIGITS.fullmatch(parts[i + 1]):
        return 0
    if i + 2 < len(parts) and _TWO_DIGITS.fullmatch(parts[i + 2]):
        return 3 if _valid_date(part, parts[i + 1], parts[i + 2]) else 0
    return 2 if _valid_date(part, parts[i + 1], None) else 0


def _is_dated_slug(segment: str) -> bool:
    """날짜와 글자 단어로만 이어지고 단어가 하나 이상이면 slug(`2026-11-26-launching`)."""
    parts = segment.split("-")
    i, words = 0, 0
    while i < len(parts):
        if _is_word(parts[i]):
            words += 1
            i += 1
            continue
        step = _date_len(parts, i)
        if not step:
            return False
        i += step
    return words >= 1


def _is_slug(segment: str) -> bool:
    """사람이 읽는 slug: 글자만 있는 단어가 둘 이상이거나, 날짜와 글자 단어로만 이뤄졌다."""
    if sum(1 for part in segment.split("-") if part.isalpha()) >= 2:
        return True
    return _is_dated_slug(segment)


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
