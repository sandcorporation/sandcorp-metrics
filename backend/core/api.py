"""HTTP API(django-ninja). 공개 경로와 관리 경로(`/api/admin/...`, 스코프 admin)를 함께 둔다."""

import json
from collections.abc import Callable
from datetime import datetime

from django.core.cache import cache
from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse
from django.http.request import RawPostDataException
from django.utils import timezone
from ninja import NinjaAPI, Schema, Status
from sandcorp_authkit.django import install_bearer_errors
from sandcorp_authkit.tokens import AccessToken

from core.clientip import client_ip
from core.schemas import SiteStatsResponse, StatsResponse, numbers, site_numbers
from metrics.models import Site
from oauth.auth import admin_auth
from services.collect import record
from services.stats import all_summaries, combine, site_summary

api = NinjaAPI(title="Sandcorp Metrics", docs_url=None)
install_bearer_errors(api)


class Health(Schema):
    status: str
    db: str


class WhoAmI(Schema):
    sub: str
    client_id: str
    scopes: list[str]
    expires_at: int


@api.get("/health", response={200: Health, 503: Health}, auth=None)
def health(request: HttpRequest) -> Status[Health]:
    """DB까지 한 번 왕복한다. compose 헬스체크와 deploy.sh가 부른다."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return Status(503, Health(status="error", db="unavailable"))
    return Status(200, Health(status="ok", db="ok"))


@api.get("/admin/whoami", response=WhoAmI, auth=admin_auth)
def whoami(request: HttpRequest) -> WhoAmI:
    """토큰 확인용: 검증된 토큰의 주체와 스코프."""
    token = getattr(request, "auth", None)  # BearerAuth가 AccessToken을 둔다
    if not isinstance(token, AccessToken):
        raise RuntimeError("whoami outside a BearerAuth endpoint")
    return WhoAmI(
        sub=token.sub, client_id=token.client_id, scopes=sorted(token.scopes), expires_at=token.exp
    )


COLLECT_MAX_BODY = 1024
# 스니펫은 어느 사이트에서든 부르므로 이 경로만 CORS `*`(다른 API에는 붙이지 않는다).
COLLECT_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


def _accepted(status: int = 202) -> HttpResponse:
    response = HttpResponse(status=status)
    for name, value in COLLECT_CORS.items():
        response[name] = value
    return response


def _read_payload(request: HttpRequest) -> object:
    """1KB 이하 JSON 본문. 크거나 JSON이 아니면 None."""
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > COLLECT_MAX_BODY:
            return None
        body = request.body
    except ValueError, RawPostDataException:
        return None
    if len(body) > COLLECT_MAX_BODY:
        return None
    try:
        parsed: object = json.loads(body)
    except ValueError, UnicodeDecodeError:
        return None
    return parsed


@api.post("/collect", auth=None, include_in_schema=False)
def collect(request: HttpRequest) -> HttpResponse:
    """조회 한 건. 저장하든 버리든 언제나 202 빈 본문(무엇이 틀렸는지 알려 주지 않는다).

    스니펫은 `sendBeacon`(text/plain)으로 보내 preflight가 없다.
    쿠키를 쓰지 않으니 CSRF 검사도 없다.
    """
    payload = _read_payload(request)
    if payload is not None:
        record(payload, client_ip(request), request.META.get("HTTP_USER_AGENT", ""), timezone.now())
    return _accepted()


@api.api_operation(["OPTIONS"], "/collect", auth=None, include_in_schema=False)
def collect_preflight(request: HttpRequest) -> HttpResponse:
    """`fetch`로 보낼 때의 preflight(204)."""
    return _accepted(204)


STATS_TTL = 60
# 공개 집계는 어느 사이트에서든 읽는다(숫자만). 읽기 전용 GET에만 CORS `*`.
STATS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": f"public, max-age={STATS_TTL}",
}


def _stats_response(body: str, status: int = 200) -> HttpResponse:
    response = HttpResponse(body, status=status, content_type="application/json")
    for name, value in STATS_HEADERS.items():
        response[name] = value
    return response


def _cached(name: str, now: datetime, build: Callable[[], str]) -> str:
    """분 단위 시각을 키에 넣어 60초 안쪽으로만 묵힌다(JSON 문자열을 캐시)."""
    key = f"stats:{name}:{now:%Y%m%d%H%M}"
    body: str | None = cache.get(key)
    if body is None:
        body = build()
        cache.set(key, body, STATS_TTL)
    return body


@api.get("/stats", auth=None, response=StatsResponse)
def public_stats(request: HttpRequest) -> HttpResponse:
    """켜진 사이트 전체의 숫자와 합계. 60초 캐시."""
    now = timezone.now()

    def build() -> str:
        pairs = all_summaries(now)
        return StatsResponse(
            sites=[site_numbers(site, summary) for site, summary in pairs],
            total=numbers(combine([summary for _, summary in pairs])),
            generated_at=now,
        ).model_dump_json()

    return _stats_response(_cached("all", now, build))


@api.get("/sites/{key}/stats", auth=None, response=SiteStatsResponse)
def public_site_stats(request: HttpRequest, key: str) -> HttpResponse:
    """한 사이트의 숫자. 모르는 키·꺼진 사이트는 404."""
    now = timezone.now()
    site = Site.objects.filter(key=key, is_active=True).first()
    if site is None:
        return _stats_response(json.dumps({"detail": "unknown site"}), status=404)

    def build() -> str:
        return SiteStatsResponse(
            **site_numbers(site, site_summary(site, now)).model_dump(), generated_at=now
        ).model_dump_json()

    return _stats_response(_cached(f"site:{site.key}", now, build))
