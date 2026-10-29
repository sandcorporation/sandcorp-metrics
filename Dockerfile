# syntax=docker/dockerfile:1
# 이미지 하나(web·scheduler 공용). oracle(arm64)에서 Jenkins가 네이티브로 빌드하고, 로컬 확인용으로 x86에서도 빌드된다.
# 프런트 번들은 없다. 정적 파일(admin, 이후 m.js)은 collectstatic 결과를 whitenoise가 낸다.

# Python 의존성. mysqlclient는 Linux 휠이 없어 여기서 MariaDB Connector/C 헤더
# (`default-libmysqlclient-dev`)로 컴파일한다. 실행 단계에는 공유 라이브러리만 있으면 된다.
# sandcorp-authkit은 private 저장소(sandcorp-auth)에서 git으로 받는다 → git·openssh-client가 필요하고,
# SSH 키는 `--mount=type=ssh`로만 빌드에 건네므로 이미지 레이어에 남지 않는다(`docker build --ssh default`).
# known_hosts도 이 빌드 단계에만 있고 runtime 단계로는 /opt/venv만 복사한다.
FROM python:3.14-slim AS pydeps
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential pkg-config default-libmysqlclient-dev \
    git openssh-client \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p -m 0700 /root/.ssh \
 && ssh-keyscan github.com >> /root/.ssh/known_hosts
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=ssh uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim AS runtime
# libmariadb3: mysqlclient가 링크하는 클라이언트 라이브러리.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmariadb3 \
 && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/backend
COPY --from=pydeps /opt/venv /opt/venv
COPY backend/ ./
RUN DJANGO_SECRET_KEY=collectstatic-only DJANGO_ADMIN_PATH=collectstatic-only \
    python manage.py collectstatic --noinput \
 && useradd --uid 1000 --no-create-home app
USER app
EXPOSE 8000
# 접근 로그는 끈다(IP·UA·URL을 남기지 않는다). 오류 로그만 stderr로.
# 제어 소켓은 쓰지 않는다(홈 디렉터리 없는 app 사용자라 만들지 못하고 오류만 남긴다).
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-2} --timeout 30 --no-control-socket"]
