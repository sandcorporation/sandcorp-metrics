/* Sandcorp Metrics 스니펫: <script defer src="https://metrics.sandcorp.co.kr/m.js" data-site="키"></script>
   쿠키 없음. 로드 1회 + SPA 경로 변경마다 조회 한 건. 끄기: localStorage.sandcorp_metrics_ignore = "1" */
(function () {
  try {
    var d = document, n = navigator, w = window, h = history, s = d.currentScript;
    var key = s && s.getAttribute("data-site");
    if (!key || n.webdriver) return;
    try { if (localStorage.getItem("sandcorp_metrics_ignore") === "1") return; } catch (e) {}
    var end = new URL(s.src).origin + "/api/collect", last, ref = d.referrer;
    var send = function () {
      try {
        var path = location.pathname;
        if (path === last) return;
        last = path;
        var body = JSON.stringify({ s: key, u: location.href, r: ref });
        ref = "";
        if (!(n.sendBeacon && n.sendBeacon(end, body)))
          fetch(end, { method: "POST", body: body, keepalive: true, mode: "no-cors" })["catch"](function () {});
      } catch (e) {}
    };
    var wrap = function (name) {
      var orig = h[name];
      h[name] = function () {
        var out = orig.apply(this, arguments);
        send();
        return out;
      };
    };
    wrap("pushState");
    wrap("replaceState");
    w.addEventListener("popstate", send);
    send();
  } catch (e) {}
})();
