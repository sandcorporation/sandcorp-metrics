#!/usr/bin/env bash
# Jenkins가 oracle 에이전트에서 잡 워크스페이스(./.env가 있는 곳, 저장소 밖)로 부른다.
#   1) 이미지: METRICS_IMAGE가 있으면(Jenkins) pull만, 없으면(make prod-local) 로컬 빌드(--ssh default: private 의존성 sandcorp-authkit)  2) DB(OCI MySQL HeatWave,
#   .env의 DB_*)가 답할 때까지 대기  3) 일회용 컨테이너로 migrate·createcachetable
#   4) web 교체  5) 헬스체크(DB 왕복) 대기  6) scheduler 교체
# migrate는 옛 web이 서비스하는 동안 돈다. 파괴적인 스키마 변경은 배포 두 번에 나눈다.
# `make prod-local`도 같은 스크립트를 COMPOSE_PROJECT_NAME=metrics-local로 돌린다.
set -euo pipefail

if [ ! -f .env ]; then
  echo "워크스페이스에 .env가 없다. .env.example을 보고 만들어 두어야 한다." >&2
  exit 1
fi

compose() { docker compose "$@"; }

wait_healthy() {
  local svc=$1
  for i in $(seq 1 90); do
    local id status
    id=$(compose ps -q "$svc")
    status=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo starting)
    if [ "$status" = "healthy" ]; then
      echo "$svc healthy (${i}회째)"
      return 0
    fi
    sleep 2
  done
  echo "$svc가 healthy가 되지 않았다" >&2
  compose logs --tail 80 "$svc" >&2
  return 1
}

if [ -n "${METRICS_IMAGE:-}" ]; then
  # Jenkins(#18): oracle 밖에서 구워 ghcr에 올린 <커밋 sha> 이미지를 받기만 한다. ghcr 읽기 로그인은 호스트 docker 설정에 있다.
  echo "== 이미지 pull ($METRICS_IMAGE)"
  docker pull "$METRICS_IMAGE"
  BUILD_FLAG=--no-build
else
  echo "== 이미지 빌드 (로컬)"
  # sandcorp-authkit(private 저장소)을 받으려면 BuildKit에 SSH를 건네야 한다(`--ssh default`).
  # GIT_SSH_KEY(키 파일 경로)가 있으면 임시 ssh-agent에 올려 쓰고 끝나면 내린다. 없으면 개발자의 SSH agent를 쓴다.
  if [ -n "${GIT_SSH_KEY:-}" ]; then
    eval "$(ssh-agent -s)" >/dev/null
    trap 'ssh-agent -k >/dev/null 2>&1 || true' EXIT
    ssh-add "$GIT_SSH_KEY" >/dev/null 2>&1
  fi
  compose build --ssh default web
  BUILD_FLAG=
fi

# 운영 DB는 compose 밖(OCI MySQL HeatWave)이다. mysql 서비스는 make prod-local 덮어쓰기에만 있다.
if compose config --services | grep -qx mysql; then
  echo "== 로컬 MySQL (prod-local, 이미 떠 있으면 그대로)"
  compose up -d --no-recreate mysql
  wait_healthy mysql
fi

echo "== DB 접속 대기"
compose run --rm --no-deps web python manage.py wait_for_db --timeout 120

echo "== migrate"
compose run --rm --no-deps web python manage.py migrate --noinput
# DB 캐시 테이블(django_cache: 공개 집계 60초 캐시 등).
compose run --rm --no-deps web python manage.py createcachetable

echo "== web 교체"
# --force-recreate: 새로 빌드한 이미지라도 compose가 "Running"으로 두고 넘어가는 경우가 있었다.
compose up -d --no-deps $BUILD_FLAG --force-recreate web
wait_healthy web

echo "== scheduler 교체 (같은 이미지)"
compose up -d --no-deps $BUILD_FLAG --force-recreate scheduler

echo "== 헬스 확인"
compose exec -T web python -c "
import os, urllib.request as u
host = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost').split(',')[0].strip()
print(u.urlopen(u.Request('http://127.0.0.1:8000/api/health', headers={'Host': host}), timeout=5).read().decode())
"
compose ps
if [ -n "${METRICS_IMAGE:-}" ]; then
  # pull 한 옛 sha 이미지는 prune에 안 걸린다 — 최신 3개만 남긴다(되돌리기는 다시 pull).
  docker image ls --format '{{.Repository}}:{{.Tag}}' "${METRICS_IMAGE%:*}" | tail -n +4 | xargs -r docker rmi >/dev/null 2>&1 || true
fi
docker image prune -f --filter label=com.docker.compose.project=metrics >/dev/null || true
