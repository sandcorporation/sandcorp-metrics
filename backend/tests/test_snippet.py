"""스니펫 GET /m.js."""

from django.test import Client

from metrics.views import SNIPPET


def test_snippet_is_at_most_1536_bytes() -> None:
    assert len(SNIPPET.read_bytes()) <= 1536


def test_snippet_response_headers() -> None:
    response = Client().get("/m.js")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/javascript")
    assert response["Cache-Control"] == "public, max-age=86400"
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response.content == SNIPPET.read_bytes()


def test_snippet_sends_on_load_and_spa_navigation_and_honours_opt_out() -> None:
    source = SNIPPET.read_text()
    for needle in (
        "sendBeacon",
        "keepalive",
        "pushState",
        "replaceState",
        "popstate",
        "sandcorp_metrics_ignore",
        "webdriver",
        "/api/collect",
        "data-site",
    ):
        assert needle in source
    assert source.lstrip().startswith("/*") and "(function () {" in source


def test_snippet_allows_head_and_rejects_post() -> None:
    assert Client().head("/m.js").status_code == 200
    assert Client().post("/m.js").status_code == 405
