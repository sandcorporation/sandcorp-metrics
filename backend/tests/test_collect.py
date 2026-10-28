"""조회 받기: POST /api/collect와 규칙(services.collect.record).

저장되든 버려지든 응답은 언제나 같은 202 빈 본문이다.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from django.test import Client
from django.utils import timezone
from pytest_django.fixtures import Settings

from metrics.models import PageView, Site
from services.collect import normalize_path, record, referrer_host

pytestmark = pytest.mark.django_db

CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"
NOW = datetime(2026, 10, 23, 3, 0, tzinfo=UTC)


@pytest.fixture
def site() -> Site:
    return Site.objects.create(key="t", name="시험", allowed_hosts="t.example, www.t.example")


def post(client: Client, body: object, *, ua: str = CHROME, xff: str = "1.2.3.4") -> None:
    data = body if isinstance(body, str | bytes) else json.dumps(body)
    response = client.post(
        "/api/collect",
        data=data,
        content_type="text/plain;charset=UTF-8",
        headers={"user-agent": ua, "x-forwarded-for": xff},
    )
    assert response.status_code == 202
    assert response.content == b""
    assert response["Access-Control-Allow-Origin"] == "*"


def hit(path: str = "/a", **more: str) -> dict[str, str]:
    return {"s": "t", "u": f"https://t.example{path}", "r": "", **more}


def test_valid_view_is_stored(site: Site) -> None:
    post(Client(), hit("/a?x=1#y", r="https://www.google.com/search?q=1"))
    view = PageView.objects.get()
    assert (view.site, view.path, view.referrer_host) == (site, "/a", "www.google.com")
    assert len(view.visitor) == 32


@pytest.mark.parametrize(
    ("body", "ua"),
    [
        pytest.param({"s": "nope", "u": "https://t.example/"}, CHROME, id="사이트 없음"),
        pytest.param({"s": "t", "u": "https://evil.example/"}, CHROME, id="호스트 불일치"),
        pytest.param({"s": "t", "u": "https://t.example/"}, "Googlebot/2.1", id="봇"),
        pytest.param({"s": "t", "u": "https://t.example/"}, "", id="빈 UA"),
        pytest.param({"s": "t", "u": "https://t.example/" + "a" * 1100}, CHROME, id="본문 초과"),
        pytest.param("not json{", CHROME, id="JSON 아님"),
        pytest.param([1, 2], CHROME, id="객체 아님"),
        pytest.param({"s": "t", "u": 5}, CHROME, id="u 문자열 아님"),
        pytest.param({"s": "t"}, CHROME, id="u 없음"),
    ],
)
def test_rejections_are_202_and_store_nothing(site: Site, body: object, ua: str) -> None:
    post(Client(), body, ua=ua)
    assert PageView.objects.count() == 0


def test_inactive_site_is_rejected(site: Site) -> None:
    site.is_active = False
    site.save()
    post(Client(), hit())
    assert PageView.objects.count() == 0


def test_same_visitor_same_path_within_5s_is_dropped(site: Site) -> None:
    client = Client()
    post(client, hit("/a"))
    post(client, hit("/a?again"))
    post(client, hit("/b"))
    assert sorted(PageView.objects.values_list("path", flat=True)) == ["/a", "/b"]


def test_dedup_window_is_5_seconds(site: Site) -> None:
    payload = hit("/a")
    assert record(payload, "1.2.3.4", CHROME, NOW)
    assert not record(payload, "1.2.3.4", CHROME, NOW + timedelta(seconds=4))
    assert record(payload, "1.2.3.4", CHROME, NOW + timedelta(seconds=6))
    assert record(payload, "5.6.7.8", CHROME, NOW + timedelta(seconds=6))


def test_path_normalization() -> None:
    assert normalize_path("https://t.example/a/b?q=1#x") == "/a/b"
    assert normalize_path("https://t.example") == "/"
    assert normalize_path("https://t.example/" + "x" * 600) == "/" + "x" * 511
    assert normalize_path("http://[::1") == "/"


def test_referrer_keeps_host_only_and_blanks_same_site() -> None:
    hosts = frozenset({"t.example", "www.t.example"})
    assert referrer_host("https://News.Example:8443/p?q=secret", hosts) == "news.example"
    assert referrer_host("https://www.t.example/prev", hosts) == ""
    assert referrer_host("", hosts) == ""
    assert referrer_host("not a url", hosts) == ""


def test_allowed_host_ignores_case_and_port(site: Site) -> None:
    assert record({"s": "t", "u": "https://WWW.T.example:443/x"}, "1.2.3.4", CHROME, NOW)


@pytest.mark.parametrize(("hops", "xff"), [(1, "6.6.6.6, 1.2.3.4"), (2, "1.2.3.4, 10.0.0.9")])
def test_visitor_uses_ip_from_forwarded_for(
    site: Site, settings: Settings, hops: int, xff: str
) -> None:
    """PROXY_HOPS번째 IP가 같으면 같은 방문자(위조 가능한 왼쪽 값은 무시)."""
    settings.PROXY_HOPS = hops
    post(Client(), hit("/a"), xff=xff)
    expected = PageView.objects.get().visitor
    PageView.objects.all().delete()
    # 뷰는 실제 시각의 소금을 쓴다 — 고정 NOW(다른 날)로 부르면 해시가 달라진다.
    assert record(hit("/a"), "1.2.3.4", CHROME, timezone.now())
    assert PageView.objects.get().visitor == expected


def test_preflight_allows_post_from_anywhere() -> None:
    response = Client().options("/api/collect", HTTP_ORIGIN="https://t.example")
    assert response.status_code == 204
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Access-Control-Allow-Methods"] == "POST"
    assert response["Access-Control-Allow-Headers"] == "Content-Type"
    assert response["Access-Control-Max-Age"] == "86400"


def test_csrf_is_not_required(site: Site) -> None:
    post(Client(enforce_csrf_checks=True), hit())
    assert PageView.objects.count() == 1


def test_other_api_paths_get_no_cors() -> None:
    assert "Access-Control-Allow-Origin" not in Client().get("/api/health")


def test_nothing_identifying_is_logged(site: Site, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    post(Client(), hit("/secret-path", r="https://ref.example/x"))
    post(Client(), "broken", ua="curl/8")
    text = caplog.text
    for needle in ("1.2.3.4", "Chrome/141", "secret-path", "ref.example", "curl"):
        assert needle not in text
