# 이미지를 oracle 밖에서 굽기 (#18)

oracle(aarch64, 4코어)은 운영 서비스 여럿이 CPU를 나눠 쓴다. 배포마다 거기서 이미지를 빌드하면 다른 서비스가 느려진다.
그래서 **이미지는 다른 노드에서 굽고 ghcr에 올리며, oracle은 받아서 교체만 한다.** 패턴 원본은 `sandcorporation/AI-Trend-News`의 `docs/ops/offhost-build.md`(#142)이고 이 저장소는 그대로 옮겼다.

## 흐름

```
main push ─▶ 이미지 빌드 ───────────────────▶ 배포(oracle)
             macos (arm64 네이티브)             docker pull ghcr.io/sandcorporation/sandcorp-metrics:<sha>
             └ 3분 안에 실행기를 못 잡으면       wait_for_db → migrate → web·scheduler 교체 → 헬스 확인
               sub(built-in, QEMU로 arm64)       (빌드 없음)
```

- **노드를 못 잡았을 때만** sub로 넘어간다. macos에서 빌드가 실패하면 실패로 끝낸다.
- 빌드 노드는 콘솔(`== 빌드 노드: macos (...)`)·빌드 설명(`<sha12> · 빌드 macos · oracle pull`)·디스코드 알림에 남는다.
- 이미지: `ghcr.io/sandcorporation/sandcorp-metrics:<커밋 sha 40자>`. 빌드 캐시는 `sandcorp-metrics-buildcache:arm64`(레지스트리).
- 스크립트 `scripts/ci/build-image.sh <macos|sub>`, 단계 정의는 `Jenkinsfile`, 이미지 변수는 `METRICS_IMAGE`(compose의 `image:`와 `deploy/deploy.sh`). 변수가 없으면(`make prod-local`) 로컬에서 빌드한다.
- 자격: ghcr 쓰기 `ghcr-push-token`, 비공개 의존성(sandcorp-authkit)용 SSH `github-farrar142`. oracle은 호스트 docker 설정의 ghcr **읽기** 로그인을 쓴다.

## 파라미터

| 이름 | 기본 | 뜻 |
|---|---|---|
| `BUILDER` | `auto` | `auto` / `macos` / `sub` — 시험용으로 빌드 노드를 강제 |
| `MAC_WAIT_SECONDS` | `180` | auto에서 macos 실행기를 기다리는 시간. 넘으면 sub |
| `ROLLBACK_SHA` | 빈 값 | 채우면 빌드 없이 그 커밋의 이미지로 되돌린다 |

## 이전 sha로 되돌리기

Jenkins `sandcorp-metrics`를 「Build with Parameters」로 `ROLLBACK_SHA=<되돌릴 커밋 sha 40자>`를 넣고 돌린다. 빌드 단계는 건너뛰고 oracle이 그 sha 이미지를 pull해 같은 migrate·교체·헬스 절차를 밟는다.
- ghcr에 그 sha 이미지가 있어야 한다(oracle에는 최신 3개만 남긴다).
- migrate는 앞으로만 간다. 되돌린 코드가 새 스키마를 못 읽으면 DB를 따로 되돌려야 한다(파괴적 스키마 변경은 두 번에 나눠 배포).

## 주의점

- Jenkins 스크립트 승인이 필요한 API(`Jenkins.instance` 등)를 쓰지 않는다.
- macos 실행기는 1개이고 다른 열차와 나눠 쓴다. 대기가 3분을 넘으면 sub로 간다.
- 배포 단계의 체크아웃은 `sandcorp-metrics` 워크스페이스(`.env`가 있는 곳)를 그대로 쓴다.
- 빌드 노드의 `buildx`에 `docker-container` 빌더가 필요하다(스크립트가 `metrics-images`를 만든다).
