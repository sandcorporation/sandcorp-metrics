# 이미지를 oracle 밖에서 굽기 (#18)

oracle(aarch64, 4코어)은 운영 서비스 여럿이 CPU를 나눠 쓴다. 배포마다 거기서 이미지를 빌드하면 다른 서비스가 느려진다.
그래서 **이미지는 다른 노드에서 굽고 ghcr에 올리며, oracle은 받아서 교체만 한다.** 패턴 원본은 `sandcorporation/AI-Trend-News`의 `docs/ops/offhost-build.md`(#142)이고 이 저장소는 그대로 옮겼다.

## 지금: Actions가 검사·굽고 production을 승격, Jenkins는 production만 배포 (#32, 2026-11-09)

```
PR ─▶ pr-check(Actions) ─▶ main 병합
main push ─▶ Actions release.yml
               check   (pr-check.yml을 workflow_call — PR과 같은 린트·타입·시험·승격 스크립트 시험)
               image   needs check — image.yml(workflow_call, ubuntu-24.04-arm matrix) ─▶ ghcr.io/sandcorporation/sandcorp-metrics:<sha>
               promote needs check·image — production 브랜치를 <sha>로 fast-forward(GITHUB_TOKEN, contents: write는 이 잡만)
production push(웹훅) ─▶ Jenkins sandcorp-metrics(잡 브랜치 */production)
               굽지 않음·검사 없음 → oracle: 이미지가 ghcr에 있는지(상한 5분) → pull → migrate·교체·헬스
```

- **production 브랜치 머리 = 운영 버전.** main 검사가 깨지면 이미지도 승격도 없다.
- 승격은 `scripts/ci/promote.sh ff <sha>`: fast-forward만(강제 없음). production이 이미 더 새 판이면(옛 실행이 늦게 끝남) 실패가 아니라 「건너뜀」. 승격은 concurrency 그룹 `production-branch`로 하나씩. 시험은 `scripts/ci/promote_test.sh`(pr-check가 돌린다).
- GITHUB_TOKEN의 push는 다른 워크플로를 깨우지 않는다(production push로 Actions가 다시 돌지 않는다). 저장소 웹훅은 깨운다 — Jenkins `githubPush`가 그것을 받는다.
- main push도 웹훅으로 Jenkins를 깨우지만 production이 움직이지 않았으면 「이미 배포에 성공한 sha」로 `NOT_BUILT`.
- Jenkins 쪽 규칙은 jenkins-shared `sandcorpDeploy(deployFrom: 'production')`(README 「승격 브랜치에서 배포」). 배포 결과는 커밋 상태 `sandcorp/deploy`·실패 PR 댓글·디스코드 `[Metrics]`로 남는다. 자동 롤백은 끔(`autoRollback: false` — `deploy/deploy.sh`가 되돌리기 재실행을 감당하지 않는다).
- 이미지 워크플로: 이미지마다 잡 하나(`strategy.matrix.include`, `fail-fast: false`). 이미지가 여럿인 저장소는 include에 한 줄씩 더하고 같은 목록을 `Jenkinsfile`의 `images`에도 적는다. 빌드 인자 `AUTHKIT_VIA_HTTPS=1`(공개 저장소 sandcorp-auth를 https로 — 비밀 아님), 캐시는 같은 패키지의 `:buildcache` 태그.
- GITHUB_TOKEN으로 push하려면 ghcr 패키지 `sandcorp-metrics`의 「Manage Actions access」에 이 저장소가 Write로 있어야 한다.
- 보안: `pull_request_target` 없음, GitHub 호스팅 실행기만, 액션 SHA 고정, GITHUB_TOKEN 말고 secrets 없음, 워크플로 기본 권한 없음(잡마다 최소).
- production 브랜치 보호: ruleset `production: ff만`(조율자가 건다) — 강제 push(`non_fast_forward`)·삭제(`deletion`) 금지, bypass는 조직 관리자만. **production은 앞으로만 간다.**
  GitHub Actions 앱을 bypass로 두는 것은 GitHub이 거절하고(422 「must be part of the ruleset source or owner organization」) classic 보호의 `restrictions apps`도 먹지 않아, 「Actions만 push」는 강제할 수 없다 — 사람이 production에 손으로 push하지 않는 것은 약속이다(그래도 fast-forward만 되니 main을 건너뛴 옛 판으로 돌릴 수는 없다).

### 다른 저장소로 펼치기

1. `pr-check.yml`에 `workflow_call:`을 더하고 `push: main`을 뺀다(캐시 저장 조건 `github.event_name == 'push'`는 그대로 main에서 돈다). concurrency 그룹은 `pr-check-${{ github.event.pull_request.number || github.sha }}`.
2. 이미지 워크플로를 `workflow_call` + `workflow_dispatch`로.
3. `release.yml`·`scripts/ci/promote.sh`·`promote_test.sh`를 그대로 복사한다(pr-check에 `bash scripts/ci/promote_test.sh` 단계).
4. Jenkinsfile을 `sandcorpDeploy(... deployFrom: 'production', images: [...])`로(이미 sandcorpDeploy를 쓰면 인자 하나 더하기).
5. production 브랜치를 지금 운영 sha로 만들고(`git push origin <sha>:refs/heads/production`), Jenkins 잡 브랜치 지정자를 `*/production`으로 바꾸고(Build Now 한 번으로 확인), ruleset을 건다:

```sh
gh api -X POST repos/sandcorporation/<저장소>/rulesets --input - <<'J'
{"name":"production: ff만","target":"branch","enforcement":"active",
 "conditions":{"ref_name":{"include":["refs/heads/production"],"exclude":[]}},
 "rules":[{"type":"non_fast_forward"},{"type":"deletion"}],
 "bypass_actors":[{"actor_id":null,"actor_type":"OrganizationAdmin","bypass_mode":"always"}]}
J
```
   `update` 규칙(push 자체 금지)은 걸지 않는다 — GitHub Actions를 bypass로 둘 수 없어 승격까지 막힌다.

## 비상 길: Jenkins가 oracle 밖에서 굽는다 (`BUILD_ON=jenkins`)

Actions가 못 구울 때 Jenkins 「Build with Parameters」에서 `BUILD_ON=jenkins`. 지금 production 머리를 굽고 배포한다(검사·대기 없음).

```
production ─▶ 이미지 빌드 ─────────────────▶ 배포(oracle)
             macos (arm64 네이티브)             docker pull ghcr.io/sandcorporation/sandcorp-metrics:<sha>
             └ 3분 안에 실행기를 못 잡으면       wait_for_db → migrate → web·scheduler 교체 → 헬스 확인
               home(built-in, QEMU로 arm64)       (빌드 없음)
```

- **노드를 못 잡았을 때만** home로 넘어간다. macos에서 빌드가 실패하면 실패로 끝낸다.
- 빌드 노드는 콘솔(`== 빌드 노드: macos (...)`)·빌드 설명(`<sha12> · 빌드 macos · oracle pull`)·디스코드 알림에 남는다.
- 이미지: `ghcr.io/sandcorporation/sandcorp-metrics:<커밋 sha 40자>`. 빌드 캐시는 `sandcorp-metrics-buildcache:arm64`(레지스트리).
- 스크립트 `scripts/ci/build-image.sh <macos|home>`(Jenkinsfile의 `buildScript`), 단계 정의는 jenkins-shared `sandcorpDeploy`, 이미지 변수는 `METRICS_IMAGE`(compose의 `image:`와 `deploy/deploy.sh`). 변수가 없으면(`make prod-local`) 로컬에서 빌드한다.
- 자격: ghcr 쓰기 `ghcr-push-token`, 비공개 의존성(sandcorp-authkit)용 SSH `github-farrar142`. oracle은 호스트 docker 설정의 ghcr **읽기** 로그인을 쓴다.

## 파라미터

| 이름 | 기본 | 뜻 |
|---|---|---|
| `BUILD_ON` | `actions` | `actions` = Actions가 구워 승격한 production 머리의 이미지를 받아 배포 / `jenkins` = 비상 길(`BUILDER`)로 굽는다 |
| `BUILDER` | `auto` | `auto` / `macos` / `home` — 시험용으로 빌드 노드를 강제 |
| `MAC_WAIT_SECONDS` | `180` | auto에서 macos 실행기를 기다리는 시간. 넘으면 home |
| `ROLLBACK_SHA` | 빈 값 | 비상 되돌리기: 채우면 빌드 없이 그 커밋의 이미지로 배포한다(production은 그대로) |

## 이전 sha로 되돌리기

production은 앞으로만 간다(강제 push 금지). 그래서 되돌리기도 「앞으로 가는 커밋」으로 한다.

**정석: main에 revert PR.** `git revert <나쁜 커밋>` → PR → pr-check 초록 → 병합. release.yml이 검사 → 이미지 → 승격(fast-forward)을 그대로 밟고 Jenkins가 그 sha를 배포한다(병합부터 승격까지 1분 30초 안팎 + 배포 1분 안팎). 운영과 main이 어긋나지 않는다.

**급할 때(검사·이미지를 기다릴 수 없을 때): Jenkins `ROLLBACK_SHA`.** `sandcorp-metrics` 「Build with Parameters」 → `ROLLBACK_SHA=<되돌릴 커밋 sha 40자>`. 굽기·검사 없이 ghcr에 그 sha 이미지가 있는지 보고(상한 5분) 지금 production의 compose·스크립트로 배포한다.
- production은 그대로라 다음 승격(main 병합)이 다시 앞으로 간다 — 곧바로 revert PR을 넣어 main을 맞춘다.
- ghcr에 그 sha 이미지가 있어야 한다(oracle에는 최신 3개만 남긴다).

공통: migrate는 앞으로만 간다. 되돌린 코드가 새 스키마를 못 읽으면 DB를 따로 되돌려야 한다(파괴적 스키마 변경은 두 번에 나눠 배포).

## 주의점

- Jenkins 스크립트 승인이 필요한 API(`Jenkins.instance` 등)를 쓰지 않는다.
- macos 실행기는 1개이고 다른 열차와 나눠 쓴다. 대기가 3분을 넘으면 home로 간다.
- 배포 단계의 체크아웃은 `sandcorp-metrics` 워크스페이스(`.env`가 있는 곳)를 그대로 쓴다.
- 빌드 노드의 `buildx`에 `docker-container` 빌더가 필요하다(스크립트가 `metrics-images`를 만든다).
