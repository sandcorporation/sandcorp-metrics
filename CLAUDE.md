# sandcorp-metrics

## Agent skills

### Issue tracker

Issues live in GitHub Issues for sandcorporation/sandcorp-metrics (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical labels: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## 작업 흐름

- 스펙은 #1, 티켓은 그 하위 이슈다.
- 이슈마다 워크트리 `~/workspace/sandcorp-metrics-wt/<브랜치>`에서 작업하고 `origin/main`으로 PR을 연다.
- PR CI는 없다. 로컬에서 `make check`(린트·타입·시험)가 통과하면 작업자가 바로 squash 병합한다(main 직접 push 금지).
- main에 병합하면 Jenkins(잡 `sandcorp-metrics`, `oracle` 에이전트)가 빌드·배포한다. 배포 잡과 서버 설정(env 파일, sandcorp-auth 클라이언트·리소스 등록, NPMplus, DNS, OCI)은 조율자가 다룬다. 작업자는 원격 호스트에 쓰지 않는다.
- 비밀 값(.env, 클라이언트 시크릿, DB 비밀번호)은 저장소에 두지 않는다. 새 설정 키는 `.env.example`에 한 줄 설명과 함께 더한다(`tests/test_settings_env.py`가 본다).
- 용어는 `GLOSSARY.md`, 결정은 `docs/adr/`를 따른다.

## 명령

저장소 루트에서 `make <대상>`. 백엔드만 있다: `backend/`(uv, Python 3.14, Django, django-ninja). 프런트 번들은 없다.

- 시험: `make test`. MySQL을 쓴다 — `make db`가 `mysql:26.10.0`(utf8mb4 / `utf8mb4_0900_as_cs`, 시험 속도용 로컬 옵션 포함)을 `metrics-dev` 프로젝트로 `127.0.0.1:15445`에 띄운다(`make test`가 알아서 부른다; `config.test_settings`가 `DB_PORT=15445`와 `DJANGO_ADMIN_PATH=admin`을 기본으로 둔다). portfolio-dev(15442)·news-dev(15443)와 함께 떠 있어도 된다. 드라이버 `mysqlclient` 빌드에는 호스트에 `pkg-config default-libmysqlclient-dev`(apt)가 있어야 한다. 시험 전체는 10초 안에 끝나야 한다.
- 시험 시간 한도: 시험 하나의 **본문 CPU 1.0초**(목표 0.5초; 현재 최댓값 0.07초). `backend/tests/conftest.py` 훅이 넘은 통과를 실패로 바꾼다(자식 프로세스 포함, 준비·정리는 안 잰다). 환경변수 `TEST_CPU_LIMIT`(초, 0이면 끔; `TEST_CPU_LIMIT=1.5 make check`)로 환경별로 보정하고, 시험 하나만 예외로 올리지 않는다 — 한도 상향은 저장소 주인이 정한다. 넘으면 한도를 올리지 말고 원인을 줄인다. 보는 법: `cd backend && uv run pytest --junitxml=/tmp/j.xml` 뒤 `python3 ~/.claude/skills/test-speed-budget/snippets/junit_slowest.py /tmp/j.xml 20 0.5`(junit 속성 `cpu_seconds`=본문 CPU, `time`은 준비 포함). 훅 확인: `TEST_CPU_LIMIT=0.001 uv run pytest <시험 하나>`가 실패해야 한다. 첫 시험의 setup 1초 남짓은 시험 DB 생성이라 한도 밖이다. MySQL은 템플릿 복제가 없고 직렬이라 따로 하지 않는다. e2e는 없다.
- 시험 위치: `backend/tests/`(pytest-django). 공용 픽스처는 `backend/tests/conftest.py` — `token_signer`(가짜 sandcorp-auth: `.issue()`·`.bearer()`로 토큰 서명), `fake_jwks`(autouse, 검증이 쓰는 JWKS·시계를 가짜로), `fake_auth_server`(admin 로그인의 `/authorize`·`/token` 흉내와 클라이언트 설정). 가짜 구현은 `sandcorp_authkit.testing`(`FakeJwks`·`FakeTokenEndpoint`·`FixedClock`).
- 린트: `make lint` (ruff format --check, ruff check). 고치기: `cd backend && uv run ruff format . && uv run ruff check --fix .`
- 타입: `make typecheck` (mypy strict + django-stubs). `Any`는 Django 명령 서명 같은 경계에만, 까닭을 주석으로.
- 전부: `make check`.
- 로컬 실행: `make dev` → http://localhost:8000 (admin `/admin/`). admin 로그인은 sandcorp-auth뿐이라 셸에 `AUTH_OWNER_SUB`·`AUTH_CLIENT_ID`·`AUTH_CLIENT_SECRET`이 없으면 로그인 화면이 503이다(API는 그대로).
- 구조: 설정 `config/settings.py`(모든 값은 환경 변수, `.env.example`), 앱 `core`(HTTP API `core/api.py`, 관리 명령 `wait_for_db`·`run_scheduler`, 클라이언트 IP `core/clientip.py` — `X-Forwarded-For` 오른쪽에서 `PROXY_HOPS`번째)와 `metrics`(모델·admin, #3부터), 규칙은 `services/`, 외부 경계는 `adapters/`(인증 경계는 `oauth/auth.py`).
- API: `GET /api/health`(DB 왕복, 200 `{"status":"ok","db":"ok"}`·503), `GET /api/admin/whoami`(스코프 admin 토큰 확인). 관리 경로는 ninja `auth=BearerAuth("admin")`.
- 공개 집계(#4): `GET /api/stats`(`sites[]`·`total`·`generated_at`)·`GET /api/sites/<key>/stats`(`core/api.py`, auth 없음, 숫자만 — 경로·리퍼러 금지). `django_cache` 60초(키에 분 단위 시각, JSON 문자열을 캐시), `Cache-Control: public, max-age=60`, CORS `*`(이 두 GET과 collect·m.js에만). 비활성·모르는 key는 404 `{"detail": "unknown site"}`. 스키마는 `core/schemas.py`(pydantic, MCP `site_stats`와 공유). 시험 설정은 캐시를 메모리로 바꾸고 테스트마다 비운다.
- 조회(#4): `services/report.py`(`daily_rows`·`top_paths`·`top_referrers` — 기간은 오늘 포함 최근 N일, 범위는 `day_start`, 빈 리퍼러(직접·같은 사이트)는 상위 리퍼러에서 뺀다). admin 「사이트 > 요약」(`SiteAdmin.summary`, `/admin/metrics/site/summary/`, 7일/30일 토글, 사이트당 쿼리 4개: 일별 2 + 경로 1 + 리퍼러 1). MCP `/mcp`(`mcpserver/`, stateless Streamable HTTP·JSON 응답·tools만, 스코프 admin; 본보기 portfolio): `whoami`·`list_sites`·`create_site`·`update_site`(`services/sites.py`)·`site_stats(key, days=30)`·`top_paths(key, days=7, limit=20)`·`top_referrers`. 도구 추가는 `mcpserver/tools.py`에 `@tool(...)`.
- 경로 마스킹(#8): `services/paths.py::mask_path`가 `normalize_path`에서 경로 조각 중 식별자처럼 보이는 것을 `*`로 바꾼 뒤 512자로 자른다(UUID, 8자 이상 16진수, 숫자만 6자리 이상, 숫자가 섞인 16자 이상 영숫자·`-`·`_` — 단 하이픈으로 나뉜 글자만 있는 단어가 둘 이상이면 slug로 보고 둔다 — , `SECRET_PREFIXES`(join·invite·reset·verify·confirm) 바로 뒤 조각은 무조건). 5초 중복 제거는 마스킹 뒤 경로로 비교한다. 기존 행은 `manage.py mask_existing_paths`(5천 건씩, 멱등, 바뀐 행 수 출력)로 한 번 적용한다.
- 수집(#3): 모델 `metrics/models.py`(`Site`·`PageView`·`DailyStat`·`DailySalt`, admin은 `Site` CRUD·`DailyStat` 읽기 전용, `PageView`·소금은 admin에 없음). `POST /api/collect`(`core/api.py`, auth 없음)는 저장 여부와 상관없이 언제나 202 빈 본문(1KB 초과·JSON 아님도), CORS `*`는 이 경로와 `/m.js`에만, `OPTIONS`는 204. 규칙은 `services/collect.py::record(payload, ip, ua, now) -> bool`(사이트 키·켜짐·URL 호스트가 `allowed_hosts`·봇 아님·빈 UA 아님·같은 방문자+경로 5초 중복 아님; 경로는 쿼리 제거 512자, 리퍼러는 호스트만이고 같은 사이트면 빈 값). 방문자 해시·소금·봇 판정은 `services/visitors.py`(소금은 DB `DailySalt`에만, 경쟁은 유일 제약), 봇 정규식 목록은 `services/bots.py` 한 곳. IP는 `core.clientip.client_ip`.
- 스니펫: `GET /m.js`는 `metrics/views.py`가 `metrics/static/metrics/m.js`를 그대로 낸다(`Cache-Control: public, max-age=86400`, CORS `*`). 1536바이트 이하(`tests/test_snippet.py`가 본다). 브라우저 동작 확인은 `scripts/check-snippet.mjs`(Node + playwright, pytest 밖): 서버를 띄우고 사이트 `t`(허용 호스트 `localhost`)를 만든 뒤 `METRICS_URL=http://127.0.0.1:<포트> node scripts/check-snippet.mjs`(playwright 위치가 다르면 `PLAYWRIGHT_MODULE=<.../playwright/index.mjs>`). 헤드리스 기본 UA는 봇으로 버려지므로 스크립트가 UA를 바꾼다.
- 주기 작업(`services/retention.py`, 명령은 `metrics/management/commands/`): `rollup_daily`(사이트마다 마지막 집계 다음 날부터 어제까지 없는 `DailyStat`을 만든다, 오늘·이미 있는 행은 건드리지 않음, 날짜 경계는 Asia/Seoul 0시를 aware datetime으로 — MySQL 시간대 표에 기대지 않는다), `prune_pageviews`(`PAGEVIEW_RETENTION_DAYS` 기본 90일, 5천 건씩), `rotate_salt`(오늘·어제 소금만 남김). `COMMANDS`가 이 순서.
- 숫자(`services/stats.py`, #4가 쓴다): `site_summary(site, now) -> Summary`(`total_visitors`·`total_pageviews` = 오늘 전 `DailyStat` 합 + 오늘, `today_*`, `live_visitors` = 최근 `LIVE_WINDOW_SECONDS`(기본 300)초 고유 방문자, `since` = 첫 집계 날짜 또는 첫 조회 날짜), `all_summaries(now)`(켜진 사이트만), `combine(summaries)`(합계). 사이트당 쿼리 3개 이하.
- 인증(sandcorp-auth 리소스 서버): **인증 코드는 sandcorp-authkit(`sandcorp_authkit`, 태그 `authkit-v0.2.0`, sandcorp-auth `clients/python/`)에서, 이 저장소에는 어댑터 한 파일(`backend/oauth/auth.py`)만.** 규칙 원본은 sandcorp-auth `docs/resource-server-token-validation.md`, 패키지 사용법은 그 `clients/python/README.md`. 어댑터가 settings(`AUTH_ISSUER`, `AUTH_RESOURCE` 기본 `SITE_URL/mcp`, `AUTH_OWNER_SUB`, `AUTH_CLIENT_*`)를 함수 인자로 바꿔 넘긴다: `admin_auth`(ninja)·`require_admin`(MCP 뷰)·`protected_resource_metadata`(`/.well-known/oauth-protected-resource`와 `/mcp` 변형; 실패 401/403, `AUTH_OWNER_SUB` 비면 503)·`login_config`. admin은 `DJANGO_ADMIN_PATH`에만 있고(없으면 기동 실패) 로그인은 sandcorp-auth 코드 플로우뿐이다: 규칙은 패키지 `login`, 이 저장소의 몫(next 검사·대표 사용자·오류 화면)은 `oauth/admin_login.py`(콜백 `<admin>/oauth/callback/`, 스코프 `login`). 시험 가짜는 `sandcorp_authkit.testing`(`tests/conftest.py`의 `token_signer`·`fake_auth_server`). 패키지는 private 저장소라 의존성 설치에 SSH가 필요하다: 로컬은 SSH 키(`uv sync`), Docker 빌드는 `docker compose build --ssh default web`(키가 agent에 없으면 `--ssh default=~/.ssh/<키>`), Jenkins는 `withCredentials`(`github-farrar142`)의 `GIT_SSH_KEY`를 `deploy/deploy.sh`가 ssh-agent로 건넨다. 패키지 버전을 올릴 때는 `pyproject.toml`의 태그를 바꾸고 `uv lock`(`--upgrade` 없이), PR 하나.
- 로그: IP·User-Agent·URL을 남기지 않는다. `django.request`·`django.server`는 ERROR만, gunicorn 접근 로그는 끔.
- 스케줄러: 운영 compose의 `scheduler` 컨테이너(같은 이미지)가 `manage.py run_scheduler`로 시작 즉시 한 번, 이후 `SCHEDULER_INTERVAL`초(기본 3600)마다 `services/scheduler.py`의 `COMMANDS`를 차례로 부른다(`--once`는 한 주기만). 새 주기 작업은 관리 명령을 만들고 `COMMANDS`에 이름을 더한다. 한 명령의 실패는 기록만 하고 계속한다.
- DB: MySQL 단일 백엔드(`mysqlclient`). 설정 `DB_HOST`·`DB_PORT`(기본 3306)·`DB_NAME`·`DB_USER`·`DB_PASSWORD`, `OPTIONS.charset=utf8mb4`, 시험 DB `utf8mb4_0900_as_cs`. 격리 수준은 Django 기본(READ COMMITTED). 캐시는 DB 캐시 `django_cache`(deploy.sh가 `createcachetable`). 운영은 compose 밖 OCI MySQL HeatWave의 `metrics` DB라 `deploy/deploy.sh`는 migrate 전에 `manage.py wait_for_db`로 접속을 기다린다.
- 운영 compose 로컬 확인: `.env.example`을 `.env`로 복사해 값을 채우고(`DJANGO_ALLOWED_HOSTS`에 `localhost`) `make prod-local`(`metrics-local` 프로젝트로 `docker-compose.prod-local.yml`이 로컬 MySQL을 더해 `deploy/deploy.sh`를 돌린다) → http://127.0.0.1:18094/api/health . 끝나면 `make prod-local-down`.
- 운영: Jenkins(`oracle` 에이전트)가 `COMPOSE_PROJECT_NAME=metrics`로 `deploy/deploy.sh`를 돌린다(빌드 → `wait_for_db` → migrate·createcachetable → web 교체 → healthy 대기 → scheduler 교체). web은 `172.17.0.1:18094`에 묶이고(`docker-compose.oracle.yml`) NPMplus가 `metrics.sandcorp.co.kr`을 거기로 보낸다. 자원 상한 web 0.5 CPU / 384m, scheduler 0.2 CPU / 192m.
- 작업자는 이 「명령」 절을 명령이 바뀌는 티켓에서 함께 고친다.
