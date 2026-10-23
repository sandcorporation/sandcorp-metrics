# 0001. 방문 메트릭은 로그 집계(Grafana/Loki)가 아니라 독립 서비스 + 스크립트 한 줄로 센다

- 상태: 채택 (2026-10-23, #1)

## 맥락

Sandcorp의 네 사이트(codemit.kr · daypage · Foresight · sandcorp.co.kr) 방문을 한곳에서 세어 sandcorp.co.kr에 「지금 · 오늘 · 누적」 숫자로 보여 주려 한다. 후보는 둘이었다. (1) 이미 있는 리버스 프록시·앱 로그를 Grafana/Loki로 모아 집계한다. (2) 각 사이트에 스크립트 한 줄을 넣고, 그것이 조회를 보내는 작은 독립 서비스를 둔다(Plausible 방식).

로그 집계는 운영 관측(오류·지연)에는 맞지만 이 목적에는 맞지 않는다. 고유 방문자를 세려면 로그에 IP·User-Agent 원본을 오래 남겨야 하고, 봇·정적 파일·헬스체크를 걸러야 하며, 공개해도 되는 숫자만 따로 뽑아 내는 경로가 또 필요하다. 네 사이트의 로그 형식과 위치도 다르다(daypage·codemit은 이 머신에 코드가 없다).

## 결정

- 독립 Django 서비스 `metrics.sandcorp.co.kr`을 둔다. 사이트는 `<script defer src=".../m.js" data-site="<키>">` 한 줄만 넣는다.
- 서비스는 조회를 받을 때 해시만 남기고(ADR 0002), 숫자는 인증 없는 공개 집계 JSON으로 낸다. 대표는 Django admin과 MCP로 본다. 따로 대시보드 화면은 만들지 않는다.
- 스택·인증·배포는 portfolio·AI-Trend-News와 같은 형태(uv·Django·ninja·MySQL HeatWave의 새 DB, sandcorp-auth 리소스 서버, Jenkins `oracle`)로 맞춘다.
- Grafana/Loki는 운영 관측용으로 나중에 따로 검토한다. 이 서비스와 섞지 않는다.

## 결과

- 사이트마다 스니펫 한 줄을 넣는 작업이 각 저장소에 생긴다(codemit은 대표가 넣는다).
- 광고 차단기가 스니펫을 막으면 그 방문은 세지 않는다. 숫자는 「대략의 규모」로 읽는다.
- 서비스 하나가 늘어 oracle 호스트에 web·scheduler 두 컨테이너(합 0.7 CPU / 576 MB 상한)가 더해진다.
