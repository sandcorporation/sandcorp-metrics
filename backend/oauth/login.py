"""Django admin login through sandcorp-auth (this site as a confidential OAuth client).

sandcorp-auth `docs/resource-server-token-validation.md` section 7, step by step:

1. `start` (`<admin>/oauth/login/`): new `state` and PKCE `code_verifier` go into the session,
   the browser goes to `/authorize` with `code_challenge` (S256), `resource`, `scope=login`.
2. The owner signs in at sandcorp-auth (password + TOTP live there, not here).
3. `callback` (`<admin>/oauth/callback/`): check `state`, trade the code at `/token`
   (`client_secret_basic`, `code_verifier`), validate the access token by the section 3 rules
   (`aud` = our resource URL, scope `login`, `sub` = `AUTH_OWNER_SUB`).
4. Log the owner's Django user in (created on first login, see `owner_user`); the token is
   dropped. From then on the admin runs on the Django session.

Any failure leaves no session and answers 403 (503 when the client is not configured);
why it failed goes to the log only.
"""

import base64
import hashlib
import logging
import secrets
import urllib.parse

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from adapters.auth_client import CodeGrant, ExchangeCode, TokenExchangeError
from oauth import bearer
from oauth.tokens import InsufficientScope, TokenRejected, validate_access_token

LOGIN_SCOPE = "login"
SESSION_KEY = "admin_oauth"

logger = logging.getLogger(__name__)


def get_exchange_code() -> ExchangeCode:
    """The token-endpoint call. Tests replace this function."""
    from adapters.auth_client import exchange_code

    return exchange_code


def authorize_url() -> str:
    return f"{bearer.issuer()}/authorize"


def redirect_uri() -> str:
    """Registered at sandcorp-auth with the client; built from settings, never the Host header."""
    return f"{settings.SITE_URL}/{settings.ADMIN_PATH}oauth/callback/"


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _configured() -> bool:
    return bool(settings.AUTH_CLIENT_ID and settings.AUTH_CLIENT_SECRET and settings.AUTH_OWNER_SUB)


def _admin_index() -> str:
    return reverse("admin:index")


def _safe_next(request: HttpRequest, candidate: str) -> str:
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return _admin_index()


def _refuse(request: HttpRequest, status: int, reason: str) -> HttpResponse:
    context = {
        **admin.site.each_context(request),
        "title": "로그인하지 못했다",
        "reason": reason,
        "login_url": reverse("admin:login"),
    }
    return TemplateResponse(request, "admin/oauth_failed.html", context, status=status)


def _not_configured(request: HttpRequest) -> HttpResponse:
    logger.error("admin OAuth login is off: AUTH_CLIENT_ID/AUTH_CLIENT_SECRET/AUTH_OWNER_SUB unset")
    return _refuse(request, 503, "sandcorp-auth 로그인이 아직 설정되지 않았다.")


def admin_login(
    request: HttpRequest, extra_context: dict[str, object] | None = None
) -> HttpResponse:
    """Replaces `admin.site.login`: there is no password form, every method goes to sandcorp-auth.

    A signed-in staff user who lands here goes on to `next` (Django's own behavior).
    """
    target = _safe_next(request, request.GET.get("next", ""))
    user = request.user
    if request.method == "GET" and user.is_active and user.is_staff:
        return HttpResponseRedirect(target)
    query = urllib.parse.urlencode({"next": target})
    return HttpResponseRedirect(f"{reverse('admin_oauth_start')}?{query}")


@require_GET
def start(request: HttpRequest) -> HttpResponse:
    if not _configured():
        return _not_configured(request)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 characters, inside RFC 7636's 43..128
    request.session[SESSION_KEY] = {
        "state": state,
        "verifier": verifier,
        "next": _safe_next(request, request.GET.get("next", "")),
    }
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.AUTH_CLIENT_ID,
            "redirect_uri": redirect_uri(),
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "resource": bearer.resource(),
            "scope": LOGIN_SCOPE,
        }
    )
    return HttpResponseRedirect(f"{authorize_url()}?{query}")


@require_GET
def callback(request: HttpRequest) -> HttpResponse:
    if not _configured():
        return _not_configured(request)
    pending = request.session.pop(SESSION_KEY, None)  # one try per start, whatever happens
    if not isinstance(pending, dict):
        logger.warning("admin OAuth callback without a pending login")
        return _refuse(request, 403, "로그인을 처음부터 다시 시작해야 한다.")
    state = request.GET.get("state", "")
    if not secrets.compare_digest(state.encode(), str(pending.get("state", "")).encode()):
        logger.warning("admin OAuth callback with a wrong state")
        return _refuse(request, 403, "로그인을 처음부터 다시 시작해야 한다.")
    error, code = request.GET.get("error"), request.GET.get("code")
    if error or not code:
        logger.warning("admin OAuth authorization failed: %s", error or "no code")
        return _refuse(request, 403, "sandcorp-auth가 로그인을 허락하지 않았다.")

    grant = CodeGrant(
        code=code,
        redirect_uri=redirect_uri(),
        code_verifier=str(pending.get("verifier", "")),
        client_id=settings.AUTH_CLIENT_ID,
        client_secret=settings.AUTH_CLIENT_SECRET,
    )
    try:
        access_token = get_exchange_code()(grant)
        token = validate_access_token(
            access_token,
            jwks=bearer.get_jwks_cache(),
            audience=bearer.resource(),
            owner_sub=settings.AUTH_OWNER_SUB,
            required_scope=LOGIN_SCOPE,
            clock=bearer.get_clock(),
            issuer=bearer.issuer(),
        )
    except (TokenExchangeError, TokenRejected, InsufficientScope) as exc:
        logger.warning("admin OAuth login refused: %s: %s", type(exc).__name__, exc)
        return _refuse(request, 403, "sandcorp-auth 토큰을 받아들이지 않았다.")

    user = owner_user(token.sub)
    if user is None:
        logger.warning("admin OAuth login refused: user %r is inactive", token.sub)
        return _refuse(request, 403, "이 계정은 막혀 있다.")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")  # new session key
    return HttpResponseRedirect(_safe_next(request, str(pending.get("next", ""))))


def owner_user(sub: str) -> User | None:
    """The owner's Django user: `username` = sandcorp-auth `sub`, staff and superuser.

    Created on the first login with an unusable password (it only ever signs in through
    sandcorp-auth). Already there: made staff/superuser again; a deactivated user stays out.
    """
    user, created = User.objects.get_or_create(
        username=sub, defaults={"is_staff": True, "is_superuser": True}
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    if not user.is_active:
        return None
    if not (user.is_staff and user.is_superuser):
        user.is_staff = user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
    return user
