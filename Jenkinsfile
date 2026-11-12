@Library('sandcorp') _

// 운영 = production 브랜치 머리(#32). 이 잡은 production만 배포한다(잡 브랜치 지정자 */production).
//
//   main push → GitHub Actions release.yml: 검사(pr-check) → 이미지(image.yml, ubuntu-24.04-arm) → production fast-forward
//   production push → 여기: 굽지도 검사하지도 않는다. ghcr.io/sandcorporation/sandcorp-metrics:<sha>가 있는지 짧게(5분) 보고
//                     oracle에서 pull → deploy/deploy.sh(wait_for_db → migrate·createcachetable → web 교체 → healthy → scheduler)
//
// 규칙은 jenkins-shared sandcorpDeploy(deployFrom) — production의 Actions-published GHCR 이미지만 배포한다.
// ROLLBACK_SHA는 이미 GHCR에 게시된 sha로 배포하는 비상 되돌리기다 — docs/ops/offhost-build.md
//
// .env는 여기서 만들지 않는다. oracle 워크스페이스에 놓아 둔 것을 compose가 ./.env로 읽는다
// (oracle 호스트의 /var/jenkins_home/workspace/sandcorp-metrics/.env).
sandcorpDeploy(
  name: 'Metrics',
  deployFrom: 'production',
  images: [[repo: 'ghcr.io/sandcorporation/sandcorp-metrics', envVar: 'METRICS_IMAGE']],
  imageWaitHint: 'https://github.com/sandcorporation/sandcorp-metrics/actions/workflows/release.yml',
  composeProject: 'metrics',
  composeFiles: ['docker-compose.prod.yml', 'docker-compose.oracle.yml'],
  // 저장소 배포 스크립트(METRICS_IMAGE·COMPOSE_PROJECT_NAME·COMPOSE_FILE을 읽는다). 되돌리기 재실행은 감당하지 않는다.
  deployScript: 'deploy/deploy.sh',
  autoRollback: false,
)
