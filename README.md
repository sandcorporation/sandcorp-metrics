# sandcorp-metrics

Sandcorp 사이트(codemit.kr, daypage, Foresight, sandcorp.co.kr) 공통 방문 메트릭 서비스. `metrics.sandcorp.co.kr`.

- 각 사이트는 `<script defer src="https://metrics.sandcorp.co.kr/m.js" data-site="<site-key>">` 한 줄만 넣는다.
- 쿠키 없이 하루 단위 해시로 방문자를 센다. IP·UA 원본은 저장하지 않는다.
- 공개 집계 JSON(누적·오늘·지금)을 포트폴리오가 읽어 보여 준다.

```sh
curl https://metrics.sandcorp.co.kr/api/stats                  # 켜진 사이트 전체 + 합계 (60초 캐시)
curl https://metrics.sandcorp.co.kr/api/sites/<site-key>/stats  # 한 사이트
```

스펙은 GitHub 이슈 #1, 작업 규칙은 `CLAUDE.md`.
