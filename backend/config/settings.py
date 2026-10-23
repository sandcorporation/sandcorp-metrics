"""Django 설정. 배포마다 다른 값은 모두 환경 변수에서 온다(/.env.example 참고)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = env("DJANGO_SECRET_KEY") or ("dev-insecure-key" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is not 1")

# Django admin은 추측하기 어려운 경로에만 둔다. 기본값을 두지 않는다 — 없으면 뜨지 않는다.
ADMIN_PATH = env("DJANGO_ADMIN_PATH").strip().strip("/")
if not ADMIN_PATH:
    raise RuntimeError("DJANGO_ADMIN_PATH is required (the admin has no default path)")
ADMIN_PATH += "/"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
# NPMplus가 TLS를 끝내고 X-Forwarded-Proto를 넘긴다.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# HTTPS로만 서비스한다. admin 세션·CSRF 쿠키를 평문 HTTP에 싣지 않는다.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "metrics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# MySQL(운영은 OCI MySQL HeatWave의 `metrics` DB, 로컬은 `make db`). DB는 utf8mb4 /
# utf8mb4_0900_as_cs로 만든다. 격리 수준은 Django 기본(READ COMMITTED)을 바꾸지 않는다.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("DB_NAME", "metrics"),
        "USER": env("DB_USER", "metrics"),
        "PASSWORD": env("DB_PASSWORD", "metrics"),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "3306"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"charset": "utf8mb4"},
        "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_0900_as_cs"},
    }
}

# gunicorn 워커끼리 나눠 쓰는 캐시(공개 집계 60초 캐시 등). 테이블은 deploy.sh가
# migrate 뒤 `manage.py createcachetable`로 만든다.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

# X-Forwarded-For를 덧붙이는 앞단 프록시 수(NPMplus = 1).
# 클라이언트 IP는 core/clientip.py로만 읽는다.
PROXY_HOPS = int(env("PROXY_HOPS", "1"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

# 이 서비스의 바깥 주소. 리소스 URL과 admin 로그인 콜백을 여기서 만든다(Host 헤더를 믿지 않는다).
SITE_URL = env("SITE_URL", "https://metrics.sandcorp.co.kr").rstrip("/")

# sandcorp-auth 리소스 서버(oauth/). 토큰의 iss는 AUTH_ISSUER, aud는 AUTH_RESOURCE와 같아야 한다.
AUTH_ISSUER = env("AUTH_ISSUER", "https://auth.sandcorp.co.kr").rstrip("/")
AUTH_RESOURCE = env("AUTH_RESOURCE", f"{SITE_URL}/mcp")
# 받아들이는 유일한 sub(대표 username). 비우면 bearer 보호 경로는 503, admin 로그인도 꺼진다.
AUTH_OWNER_SUB = env("AUTH_OWNER_SUB").strip()
# admin 로그인용 기밀 클라이언트. sandcorp-auth에 리다이렉트 URI
# `{SITE_URL}/{ADMIN_PATH}oauth/callback/`으로 등록한다. 비우면 admin 로그인만 503.
AUTH_CLIENT_ID = env("AUTH_CLIENT_ID").strip()
AUTH_CLIENT_SECRET = env("AUTH_CLIENT_SECRET").strip()

# 스케줄러(`manage.py run_scheduler`)의 주기(초).
SCHEDULER_INTERVAL = int(env("SCHEDULER_INTERVAL", "3600"))

# 정적 파일(admin, 이후 m.js)은 collectstatic 결과를 whitenoise가 낸다.
STATIC_URL = "/static/"
STATIC_ROOT = Path(env("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# 로그에 IP·User-Agent·URL을 남기지 않는다: 요청 로그(django.request, django.server)는
# 경로·상태만 적는 기본 메시지도 끄고(WARNING 이상만), 포맷에 요청 정보를 넣지 않는다.
# gunicorn 접근 로그는 Dockerfile에서 끈다.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"level": "ERROR"},
        "django.server": {"level": "ERROR"},
    },
}
