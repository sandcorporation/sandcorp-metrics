# 한 줄 명령 모음. 자세한 것은 CLAUDE.md 「명령」 절.
.PHONY: db test lint typecheck check dev prod-local prod-local-down

db:  ## 로컬 시험·개발용 MySQL 26.10 (127.0.0.1:15445, 프로젝트 metrics-dev, utf8mb4_0900_as_cs)
	docker compose up -d --wait db

# 시험 하나의 본문 CPU 한도(초). 붐비는 머신이면 `TEST_CPU_LIMIT=1.5 make check`.
TEST_CPU_LIMIT ?= 1.0
export TEST_CPU_LIMIT

test: db
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff format --check . && uv run ruff check .

typecheck:
	cd backend && uv run mypy .

check: lint typecheck test

dev: db  ## http://localhost:8000 (admin은 /admin/)
	cd backend && DB_PORT=15445 DJANGO_DEBUG=1 DJANGO_ADMIN_PATH=admin uv run python manage.py migrate --noinput
	cd backend && DB_PORT=15445 DJANGO_DEBUG=1 DJANGO_ADMIN_PATH=admin uv run python manage.py createcachetable
	cd backend && DB_PORT=15445 DJANGO_DEBUG=1 DJANGO_ADMIN_PATH=admin uv run python manage.py runserver 8000

# 운영 compose를 로컬에서 띄워 본다(.env 필요: cp .env.example .env 후 값 채우기, ALLOWED_HOSTS에 localhost 포함).
# deploy/deploy.sh와 같은 순서(빌드 → DB 대기 → migrate → web → scheduler)로 띄운다. 운영 DB 대신
# docker-compose.prod-local.yml이 로컬 MySQL을 더한다. http://127.0.0.1:18094
prod-local:
	COMPOSE_PROJECT_NAME=metrics-local COMPOSE_FILE=docker-compose.prod.yml:docker-compose.prod-local.yml bash deploy/deploy.sh

prod-local-down:
	docker compose -p metrics-local -f docker-compose.prod.yml -f docker-compose.prod-local.yml down -v
