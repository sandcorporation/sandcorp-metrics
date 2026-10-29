"""이 저장소에서 sandcorp-auth 설정(settings)을 읽는 유일한 곳 — 어댑터 한 파일.

토큰 검증·bearer·운영자 로그인 규칙은 sandcorp-authkit이 갖고 있다. 여기서는 settings를 함수
인자로 바꿔 넘기기만 한다. 시험은 `jwks_cache`·`token_transport`·`clock`을 monkeypatch한다.
"""

from functools import cache

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET
from sandcorp_authkit.django import (
    AuthNotConfigured,
    BearerAuth,
    BearerConfig,
    metadata_response,
    require_bearer,
)
from sandcorp_authkit.login import LoginConfig, TokenTransport
from sandcorp_authkit.tokens import (
    ClaimsHook,
    JwksCache,
    SystemClock,
    http_jwks_fetcher,
    owner_only,
)

SCOPES_SUPPORTED = ["admin", "login"]
MCP_SCOPE = "admin"

clock = SystemClock()


@cache  # 프로세스마다 JWKS 캐시 하나
def jwks_cache() -> JwksCache:
    return JwksCache(http_jwks_fetcher(f"{settings.AUTH_ISSUER}/.well-known/jwks.json"), clock)


def token_transport() -> TokenTransport | None:
    """`/token` 호출 방법. None이면 패키지 기본(urllib). 시험이 가짜 서버로 바꾼다."""
    return None


def owner_hook() -> ClaimsHook:
    return owner_only(str(settings.AUTH_OWNER_SUB))


def bearer_config() -> BearerConfig:
    if not settings.AUTH_OWNER_SUB:
        raise AuthNotConfigured("AUTH_OWNER_SUB is empty")  # 보호 경로는 503
    return BearerConfig(
        issuer=settings.AUTH_ISSUER,
        audience=settings.AUTH_RESOURCE,
        resource_metadata_url=f"{settings.SITE_URL}/.well-known/oauth-protected-resource",
        jwks=jwks_cache(),
        clock=clock,
        extra_claims_hook=owner_hook(),
    )


def login_config() -> LoginConfig:
    """admin 로그인용 기밀 클라이언트. 콜백은 설정에서 만든다(Host 헤더를 믿지 않는다)."""
    owner_set = bool(settings.AUTH_OWNER_SUB)
    return LoginConfig(
        client_id=settings.AUTH_CLIENT_ID,
        client_secret=settings.AUTH_CLIENT_SECRET
        if owner_set
        else "",  # 대표 sub 없으면 로그인 꺼짐
        redirect_uri=f"{settings.SITE_URL}/{settings.ADMIN_PATH}oauth/callback/",
        authorize_url=f"{settings.AUTH_ISSUER}/authorize",
        token_url=f"{settings.AUTH_ISSUER}/token",
        issuer=settings.AUTH_ISSUER,
        resource=settings.AUTH_RESOURCE,
        scope="login",
    )


admin_auth = BearerAuth(MCP_SCOPE, config=bearer_config)  # ninja: auth=admin_auth
require_admin = require_bearer(MCP_SCOPE, config=bearer_config)  # Django 뷰(MCP)


@require_GET
def protected_resource_metadata(request: HttpRequest) -> HttpResponse:
    """RFC 9728 메타데이터: MCP 클라이언트에게 sandcorp-auth가 /mcp 토큰을 발급한다고 알린다."""
    return metadata_response(settings.AUTH_RESOURCE, settings.AUTH_ISSUER, SCOPES_SUPPORTED)
