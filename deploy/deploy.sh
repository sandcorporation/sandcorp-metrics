#!/usr/bin/env bash
# Jenkins가 oracle 에이전트에서 잡 워크스페이스(./.env가 있는 곳, 저장소 밖)로 부른다.
#   1) 이미지 빌드  2) DB(OCI MySQL HeatWave, .env의 DB_*)가 답할 때까지 대기  3) 일회용 컨테이너로
#   migrate·createcachetable  4) web 교체  5) 헬스체크(DB 왕복) 대기  6) scheduler 교체
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
  for i in $(seq 1 60); do
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

echo "== 이미지 빌드"
compose build web

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
compose up -d --no-deps --force-recreate web
wait_healthy web

echo "== scheduler 교체 (같은 이미지)"
compose up -d --no-deps --force-recreate scheduler

echo "== 헬스 확인"
compose exec -T web python -c "
import os, urllib.request as u
host = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost').split(',')[0].strip()
print(u.urlopen(u.Request('http://127.0.0.1:8000/api/health', headers={'Host': host}), timeout=5).read().decode())
"
compose ps
docker image prune -f --filter label=com.docker.compose.project=metrics >/dev/null || true
