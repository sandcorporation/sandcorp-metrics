from django.conf import settings
from django.contrib import admin
from django.urls import path

from core.api import api
from oauth import login as oauth_login
from oauth.bearer import protected_resource_metadata

# 비밀번호 폼 없음: admin 로그인 화면은 sandcorp-auth 로그인의 시작이다.
admin.site.login = oauth_login.admin_login  # type: ignore[method-assign]
admin.site.site_header = admin.site.site_title = "Sandcorp Metrics"

urlpatterns = [
    # sandcorp-auth admin 로그인(admin.site.urls의 catch-all보다 앞에 둔다).
    path(f"{settings.ADMIN_PATH}oauth/login/", oauth_login.start, name="admin_oauth_start"),
    path(
        f"{settings.ADMIN_PATH}oauth/callback/", oauth_login.callback, name="admin_oauth_callback"
    ),
    path(settings.ADMIN_PATH, admin.site.urls),
    path("api/", api.urls),
    # RFC 9728: 클라이언트가 /mcp 리소스의 경로 붙은 메타데이터를 물을 수도 있어 둘 다 같은 문서.
    path(".well-known/oauth-protected-resource", protected_resource_metadata),
    path(".well-known/oauth-protected-resource/mcp", protected_resource_metadata),
]
