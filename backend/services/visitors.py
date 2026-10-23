"""방문자(Visitor): 쿠키 없는 하루 해시와 봇 판정.

`visitor = sha256(그날 소금 ‖ 사이트 키 ‖ IP ‖ User-Agent)` 앞 32자. 소금은 DB(`DailySalt`)에만 있어
프로세스가 몇 개든, 재시작하든 하루 안에서는 같은 값이 나온다. IP·UA 원본은 해시에만 쓰고 버린다.
클라이언트 IP는 `core.clientip.client_ip`로 읽는다.
"""

import hashlib
import re
import secrets
from datetime import date

from django.db import IntegrityError, transaction

from metrics.models import DailySalt
from services.bots import BOT_PATTERNS

SALT_BYTES = 32
VISITOR_LENGTH = 32

_BOT_RE = re.compile("|".join(BOT_PATTERNS), re.IGNORECASE)


def is_bot(ua: str) -> bool:
    return bool(_BOT_RE.search(ua))


def daily_salt(day: date) -> bytes:
    """그날 소금. 없으면 만든다(그날 처음 요청)."""
    found = DailySalt.objects.filter(date=day).values_list("salt", flat=True).first()
    if found is not None:
        return bytes(found)
    return insert_salt(day)


def insert_salt(day: date) -> bytes:
    """새 소금을 넣는다. 다른 요청이 먼저 넣었으면(유일 제약 위반) 그 값을 읽어 돌려준다."""
    salt = secrets.token_bytes(SALT_BYTES)
    try:
        with transaction.atomic():
            DailySalt.objects.create(date=day, salt=salt)
    except IntegrityError:
        return bytes(DailySalt.objects.get(date=day).salt)
    return salt


def visitor_hash(site_key: str, ip: str, ua: str, day: date) -> str:
    digest = hashlib.sha256()
    digest.update(daily_salt(day))
    for part in (site_key, ip, ua):
        digest.update(b"\x00" + part.encode())
    return digest.hexdigest()[:VISITOR_LENGTH]
