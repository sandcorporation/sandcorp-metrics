"""Bearer-token guard for Django views and ninja endpoints (this site is a resource server).

sandcorp-auth (https://auth.sandcorp.co.kr) issues the tokens; this site only checks them with
`oauth.tokens.validate_access_token`. Three ways to use it, all with one required scope:

- Django view:  `@require_bearer("admin")` -> the view gets `(request, token, ...)`.
- ninja:        `auth=BearerAuth("admin")` -> `request.auth` is the `AccessToken`
                (the API must call `install_bearer_errors(api)` once).
- by hand:      `authenticate(request, "admin")`, and on `AuthError` return `deny(exc)`.

Failures: no token 401, bad token 401 `invalid_token`, missing scope 403 `insufficient_scope`,
`AUTH_OWNER_SUB` unset 503. Why a token failed goes to the log, never to the response.
"""

import functools
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Concatenate, ParamSpec

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from ninja import NinjaAPI
from ninja.security.base import AuthBase

from oauth.tokens import (
    AccessToken,
    Clock,
    InsufficientScope,
    JwksCache,
    TokenRejected,
    validate_access_token,
    www_authenticate,
)

SCOPES_SUPPORTED = ["admin", "login"]


def site_origin() -> str:
    return str(settings.SITE_URL)


def resource() -> str:
    """이 서비스의 리소스 URL(`aud`). settings.AUTH_RESOURCE, 기본 `SITE_URL/mcp`."""
    return str(settings.AUTH_RESOURCE)


def issuer() -> str:
    return str(settings.AUTH_ISSUER)


logger = logging.getLogger(__name__)
P = ParamSpec("P")


class MissingToken(Exception):
    """No `Authorization: Bearer ...` header (rule B2)."""


class AuthNotConfigured(Exception):
    """`AUTH_OWNER_SUB` is empty: nobody can be the owner, so refuse everything."""


AuthError = MissingToken | AuthNotConfigured | TokenRejected | InsufficientScope
AUTH_ERRORS = (MissingToken, AuthNotConfigured, TokenRejected, InsufficientScope)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


_jwks_cache: JwksCache | None = None


def get_jwks_cache() -> JwksCache:
    """The process-wide JWKS cache (rule J1). Tests replace this function."""
    global _jwks_cache
    if _jwks_cache is None:
        from adapters.jwks import fetch_jwks

        _jwks_cache = JwksCache(
            lambda: fetch_jwks(f"{issuer()}/.well-known/jwks.json"), SystemClock()
        )
    return _jwks_cache


def get_clock() -> Clock:
    """The clock for `exp`. Tests replace this function."""
    return SystemClock()


def authenticate(request: HttpRequest, scope: str) -> AccessToken:
    """Return the verified access token for `scope`, or raise one of `AuthError`."""
    owner_sub: str = settings.AUTH_OWNER_SUB
    if not owner_sub:
        raise AuthNotConfigured
    kind, _, token = request.headers.get("Authorization", "").partition(" ")
    if kind.lower() != "bearer" or not token:
        raise MissingToken
    try:
        return validate_access_token(
            token,
            jwks=get_jwks_cache(),
            audience=resource(),
            owner_sub=owner_sub,
            required_scope=scope,
            clock=get_clock(),
            issuer=issuer(),
        )
    except TokenRejected as exc:
        logger.warning("bearer token rejected: %s (%s %s)", exc, request.method, request.path)
        raise
    except InsufficientScope as exc:
        logger.warning("bearer token lacks scope %r (%s)", exc.required_scope, request.path)
        raise


def deny(exc: AuthError) -> HttpResponse:
    """The 401/403/503 response for an `AuthError` (sandcorp-auth rules, section 5)."""
    if isinstance(exc, AuthNotConfigured):
        logger.error("AUTH_OWNER_SUB is not set: bearer-protected endpoints answer 503")
        return JsonResponse({"error": "auth_not_configured"}, status=503)
    if isinstance(exc, InsufficientScope):
        response = JsonResponse({"error": "forbidden"}, status=403)
        response["WWW-Authenticate"] = www_authenticate(
            site_origin(), error="insufficient_scope", scope=exc.required_scope
        )
        return response
    response = JsonResponse({"error": "unauthorized"}, status=401)
    response["WWW-Authenticate"] = www_authenticate(
        site_origin(), error="invalid_token" if isinstance(exc, TokenRejected) else None
    )
    return response


def require_bearer(
    scope: str,
) -> Callable[
    [Callable[Concatenate[HttpRequest, AccessToken, P], HttpResponse]],
    Callable[Concatenate[HttpRequest, P], HttpResponse],
]:
    """Guard a Django view; the view receives the verified token after the request."""

    def decorate(
        view: Callable[Concatenate[HttpRequest, AccessToken, P], HttpResponse],
    ) -> Callable[Concatenate[HttpRequest, P], HttpResponse]:
        def guarded(request: HttpRequest, /, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
            try:
                token = authenticate(request, scope)
            except AUTH_ERRORS as exc:
                return deny(exc)
            return view(request, token, *args, **kwargs)

        functools.update_wrapper(guarded, view)
        return guarded

    return decorate


class BearerAuth(AuthBase):
    """ninja auth: `auth=BearerAuth("admin")`; `request.auth` becomes the `AccessToken`."""

    openapi_type = "http"
    openapi_scheme = "bearer"

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__()

    def __call__(self, request: HttpRequest) -> AccessToken:
        return authenticate(request, self.scope)  # AuthError -> install_bearer_errors


def bearer_token(request: HttpRequest) -> AccessToken:
    """The token `BearerAuth` put on `request.auth` (inside a `BearerAuth` endpoint)."""
    token = getattr(request, "auth", None)
    if not isinstance(token, AccessToken):
        raise RuntimeError("bearer_token() outside a BearerAuth endpoint")
    return token


def install_bearer_errors(api: NinjaAPI) -> None:
    """Make `BearerAuth` failures answer like every other bearer-protected endpoint."""

    def handle(request: HttpRequest, exc: Exception | type[Exception]) -> HttpResponse:
        if not isinstance(exc, AUTH_ERRORS):
            raise TypeError(f"not a bearer error: {exc!r}")
        return deny(exc)

    for error in AUTH_ERRORS:
        api.add_exception_handler(error, handle)


@require_GET
def protected_resource_metadata(request: HttpRequest) -> HttpResponse:
    """RFC 9728 metadata: tells MCP clients that sandcorp-auth issues tokens for /mcp."""
    response = JsonResponse(
        {
            "resource": resource(),
            "authorization_servers": [issuer()],
            "scopes_supported": SCOPES_SUPPORTED,
            "bearer_methods_supported": ["header"],
        }
    )
    response["Access-Control-Allow-Origin"] = "*"  # public document; browser MCP clients read it
    return response
