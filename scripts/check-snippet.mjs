// m.js가 실제 브라우저에서 조회를 보내는지 한 번 본다(pytest 밖, 수동 확인용).
//
// 준비: 서버를 띄우고(`make dev` 등) 사이트 키 `t`, 허용 호스트 `localhost`를 만든다.
// 실행: METRICS_URL=http://127.0.0.1:8000 node scripts/check-snippet.mjs
//       (playwright 패키지 위치가 다르면 PLAYWRIGHT_MODULE=<.../playwright/index.mjs>)
//
// 정적 HTML 두 쪽(http://localhost:8795/a.html, /b.html — 서버와 다른 출처)을 node http로 띄우고, 그 안의
// <script defer src="$METRICS_URL/m.js" data-site="t">가 진짜 서버로 간다. 본다:
//   1) 로드 1회 + history.pushState로 /b.html → /api/collect 2번(같은 경로 pushState는 생략)
// 쪽도 실제 루프백 서버여야 한다(가로챈 응답은 공용 주소로 쳐서 Chromium 로컬 네트워크 접근 차단이 막는다).
//   2) navigator.webdriver면 0번   3) localStorage.sandcorp_metrics_ignore="1"이면 0번
const base = (process.env.METRICS_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const origin = "http://localhost:8795";
const { createServer } = await import("node:http");
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");

const CHROME =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36";
const page = (title) =>
  `<!doctype html><title>${title}</title><a href="/b.html">b</a>` +
  `<script defer src="${base}/m.js" data-site="t"></script>`;

async function run({ webdriver, ignore }) {
  // 헤드리스 기본 UA(HeadlessChrome)는 서버가 봇으로 버리므로 일반 크롬 UA로 바꾼다.
  const context = await browser.newContext({ userAgent: CHROME });
  if (!webdriver)
    await context.addInitScript(() =>
      Object.defineProperty(Navigator.prototype, "webdriver", { get: () => false }),
    );
  if (ignore)
    await context.addInitScript(() => localStorage.setItem("sandcorp_metrics_ignore", "1"));
  const sent = [];
  context.on("request", (req) => {
    if (req.url() === `${base}/api/collect`) sent.push(JSON.parse(req.postData() ?? "{}"));
  });
  const p = await context.newPage();
  await p.goto(`${origin}/a.html?utm=x`, { timeout: 10000 });
  await p.waitForTimeout(800);
  await p.evaluate(() => history.pushState({}, "", "/b.html"));
  await p.evaluate(() => history.pushState({}, "", "/b.html?again"));
  await p.waitForTimeout(800);
  await context.close();
  return sent;
}

const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(page(req.url));
});
await new Promise((resolve) => server.listen(8795, "localhost", resolve));
const browser = await chromium.launch();
let failed = false;
const check = (name, ok, detail) => {
  console.log(`${ok ? "OK  " : "FAIL"} ${name}: ${JSON.stringify(detail)}`);
  failed ||= !ok;
};
try {
  const normal = await run({ webdriver: false, ignore: false });
  check(
    "로드+pushState → 2건",
    normal.length === 2 &&
      normal[0].u === `${origin}/a.html?utm=x` &&
      normal[1].u === `${origin}/b.html` &&
      normal.every((b) => b.s === "t"),
    normal,
  );
  check("webdriver → 0건", (await run({ webdriver: true, ignore: false })).length === 0, []);
  check("ignore → 0건", (await run({ webdriver: false, ignore: true })).length === 0, []);
} finally {
  await browser.close();
  server.close();
}
process.exit(failed ? 1 : 0);
