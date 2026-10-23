"""HTTP API(django-ninja). 공개 경로와 관리 경로(`/api/admin/...`, 스코프 admin)를 함께 둔다."""

import json

from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse
from django.http.request import RawPostDataException
from django.utils import timezone
from ninja import NinjaAPI, Schema, Status

from core.clientip import client_ip
from oauth.bearer import BearerAuth, bearer_token, install_bearer_errors
from services.collect import record

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


@api.get("/admin/whoami", response=WhoAmI, auth=BearerAuth("admin"))
def whoami(request: HttpRequest) -> WhoAmI:
    """토큰 확인용: 검증된 토큰의 주체와 스코프."""
    token = bearer_token(request)
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
    except (ValueError, RawPostDataException):
        return None
    if len(body) > COLLECT_MAX_BODY:
        return None
    try:
        parsed: object = json.loads(body)
    except (ValueError, UnicodeDecodeError):
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
