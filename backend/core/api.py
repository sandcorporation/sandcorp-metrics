"""HTTP API(django-ninja). 공개 경로와 관리 경로(`/api/admin/...`, 스코프 admin)를 함께 둔다."""

from django.db import DatabaseError, connection
from django.http import HttpRequest
from ninja import NinjaAPI, Schema, Status

from oauth.bearer import BearerAuth, bearer_token, install_bearer_errors

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
