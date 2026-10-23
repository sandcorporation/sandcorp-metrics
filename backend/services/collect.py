"""조회 받기(`POST /api/collect`의 규칙).

어떤 거부도 예외 없이 False로 끝난다(응답은 언제나 같은 202라 무엇이 틀렸는지 새지 않는다).
IP·UA·URL은 저장하지도 로그에 남기지도 않는다.
"""

from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.utils import timezone

from metrics.models import PageView, Site
from services.visitors import is_bot, visitor_hash

PATH_MAX = 512
REFERRER_MAX = 255
DEDUP_WINDOW = timedelta(seconds=5)


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:  # 잘못된 IPv6 리터럴 같은 깨진 URL
        return ""


def normalize_path(url: str) -> str:
    """쿼리·프래그먼트를 뗀 경로(512자에서 자름). 비면 `/`."""
    try:
        path = urlsplit(url).path
    except ValueError:
        path = ""
    return (path or "/")[:PATH_MAX]


def referrer_host(referrer: str, site_hosts: frozenset[str]) -> str:
    """리퍼러의 호스트만. 같은 사이트 안에서 온 것이면 빈 값."""
    host = _host(referrer)
    return "" if host in site_hosts else host[:REFERRER_MAX]


def record(payload: object, ip: str, ua: str, now: datetime) -> bool:
    """조회 한 건을 저장하면 True. 사이트 없음·꺼짐·호스트 불일치·봇·빈 UA·5초 중복은 False."""
    if not isinstance(payload, dict):
        return False
    key, url, ref = payload.get("s"), payload.get("u"), payload.get("r", "")
    if not (isinstance(key, str) and isinstance(url, str) and isinstance(ref, str)):
        return False
    ua = ua.strip()
    if not ua or is_bot(ua):
        return False
    site = Site.objects.filter(key=key, is_active=True).first()
    if site is None:
        return False
    hosts = site.host_set()
    if _host(url) not in hosts:
        return False
    path = normalize_path(url)
    visitor = visitor_hash(site.key, ip, ua, timezone.localdate(now))
    if PageView.objects.filter(
        site=site, visitor=visitor, path=path, occurred_at__gt=now - DEDUP_WINDOW
    ).exists():
        return False
    PageView.objects.create(
        site=site,
        occurred_at=now,
        path=path,
        referrer_host=referrer_host(ref, hosts),
        visitor=visitor,
    )
    return True
