"""admin 로그인 화면·콜백 뷰(사이트 몫). 규칙(state·PKCE·nonce·교환·토큰 검증)은 sandcorp-authkit.

사이트가 하는 일: 다음으로 갈 주소(`next`)의 안전 검사, 대표의 Django 사용자 만들기·되살리기
(`owner_user`, 비활성이면 거절), 오류 화면. 실패는 세션 없이 403(클라이언트 설정이 비면 503)이고
이유는 로그에만 남는다.
"""

import logging
import urllib.parse

from django.contrib import admin
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET
from sandcorp_authkit.login import LoginRejected, SessionAttemptStore, complete_login, start_login

from oauth import auth

logger = logging.getLogger(__name__)


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
    try:
        url = start_login(
            auth.login_config(),
            SessionAttemptStore(request.session),
            clock=auth.clock,
            extra={"next": _safe_next(request, request.GET.get("next", ""))},
        )
    except LoginRejected:
        return _not_configured(request)
    return HttpResponseRedirect(url)


@require_GET
def callback(request: HttpRequest) -> HttpResponse:
    try:
        result = complete_login(
            request.GET.dict(),
            auth.login_config(),
            SessionAttemptStore(request.session),  # 시도는 한 번만: 꺼내면서 지운다
            jwks=auth.jwks_cache(),
            clock=auth.clock,
            extra_claims_hook=auth.owner_hook(),
            transport=auth.token_transport(),
        )
    except LoginRejected as exc:
        if exc.reason == "config":
            return _not_configured(request)
        logger.warning("admin OAuth login refused: %s", exc.reason)
        if exc.reason in ("state", "expired"):
            return _refuse(request, 403, "로그인을 처음부터 다시 시작해야 한다.")
        if exc.reason == "denied":
            return _refuse(request, 403, "sandcorp-auth가 로그인을 허락하지 않았다.")
        return _refuse(request, 403, "sandcorp-auth 토큰을 받아들이지 않았다.")

    user = owner_user(result.access.sub)
    if user is None:
        logger.warning("admin OAuth login refused: user %r is inactive", result.access.sub)
        return _refuse(request, 403, "이 계정은 막혀 있다.")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")  # new session key
    return HttpResponseRedirect(_safe_next(request, result.extra.get("next", "")))


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
