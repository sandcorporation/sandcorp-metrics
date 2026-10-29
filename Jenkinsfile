// main에 푸시하면 oracle(Jenkins 에이전트, arm64)에 배포한다. 잡 이름 sandcorp-metrics.
//
// .env는 여기서 만들지 않는다. 워크스페이스에 놓아 둔 것을 compose가 ./.env로 읽는다
// (oracle 호스트의 /var/jenkins_home/workspace/sandcorp-metrics/.env). checkout은 추적하지 않는 파일을 지우지 않는다.
//
// oracle의 80·443은 NPMplus가 쓴다. web은 docker 브리지 게이트웨이 172.17.0.1:18094에만 묶는다.
// NPMplus 프록시 호스트: metrics.sandcorp.co.kr → http://172.17.0.1:18094, Let's Encrypt.
//
// 시험은 로컬에서만 돌린다(CI 없음). 이 잡은 빌드·마이그레이션·교체·헬스 확인만 한다.

pipeline {
  agent { label 'oracle' }

  options {
    disableConcurrentBuilds()
    timeout(time: 30, unit: 'MINUTES')
    timestamps()
  }

  environment {
    COMPOSE_PROJECT_NAME = 'metrics'
    COMPOSE_FILE = 'docker-compose.prod.yml:docker-compose.oracle.yml'
    DOCKER_BUILDKIT = '1'
  }

  triggers {
    githubPush()
  }

  stages {
    stage('체크아웃') {
      steps {
        checkout scm
        sh 'git log --oneline -1'
      }
    }

    stage('빌드·배포') {
      steps {
        // sandcorp-authkit(private 저장소)을 SSH로 받는다. 키는 deploy.sh가 ssh-agent에 올려 빌드에만 건네고
        // 로그·이미지에 남기지 않는다. 자격 증명 ID는 Jenkins의 SSH 키 항목.
        withCredentials([sshUserPrivateKey(credentialsId: 'github-farrar142', keyFileVariable: 'GIT_SSH_KEY')]) {
          sh 'bash deploy/deploy.sh'
        }
      }
    }
  }

  post {
    // 빌드가 끝나면 디스코드로 결과를 한 줄 보낸다. 배포는 사람이 화면을 보지 않을 때 도는
    // 일이라 끝났다는 사실(특히 실패)이 사람에게 닿을 자리가 필요하다. 모든 Sandcorp 제품이
    // 같은 웹훅을 쓰고 메시지의 [Metrics] 표식으로 제품을 구분한다.
    // 웹훅 주소는 Jenkins 자격증명 discord-deploy-webhook 에 있고 여기서는 이름으로만 부른다
    // (아는 사람은 그 채널에 아무 말이나 올릴 수 있으므로 저장소·로그에 남기지 않는다).
    // 알림이 실패해도 빌드 결과를 뒤집지 않는다 — catchError 와 curl 끝의 || true 가 그 역할이다.
    always {
      script {
        catchError(buildResult: null, stageResult: null, message: '디스코드 알림 실패 — 배포 결과와 무관하다') {
          withCredentials([string(credentialsId: 'discord-deploy-webhook', variable: 'DISCORD_WEBHOOK')]) {
            def result = currentBuild.currentResult
            def mark = result == 'SUCCESS' ? '✅' : (result == 'ABORTED' ? '⚪' : '❌')
            def sha = (env.GIT_COMMIT ?: '').take(12)
            def took = currentBuild.durationString.replace(' and counting', '')
            def text = "${mark} [Metrics] 배포 ${result} — #${env.BUILD_NUMBER}" +
              (sha ? " (${sha})" : '') + " · ${took} · ${env.BUILD_URL}"
            // 본문은 JSON 이라 따옴표·역슬래시를 그대로 실으면 깨진다 — 파일로 넘겨 셸이 다시 해석하지 않게 한다.
            writeFile file: 'discord-payload.json', text: groovy.json.JsonOutput.toJson([content: text])
            sh 'curl -sS -X POST -H "Content-Type: application/json" --data @discord-payload.json "$DISCORD_WEBHOOK" > /dev/null || true'
          }
        }
      }
    }
    failure {
      echo '배포 실패 — deploy/deploy.sh 출력과 compose 로그를 보라.'
    }
  }
}
