"""admin 요약 뷰: 대표 세션으로 200과 표 내용, 사이트당 쿼리 수."""

import re
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from metrics.models import DailyStat, PageView, Site

pytestmark = pytest.mark.django_db
URL = "/admin/metrics/site/summary/"


@pytest.fixture
def owner() -> Client:
    user = User.objects.create_superuser("owner", password=None)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def site() -> Site:
    site = Site.objects.create(key="a", name="사이트A", allowed_hosts="a.kr")
    DailyStat.objects.create(
        site=site, date=timezone.localdate() - timedelta(days=2), pageviews=42, visitors=7
    )
    for visitor in ("v1", "v2"):
        PageView.objects.create(
            site=site,
            occurred_at=timezone.now(),
            path="/best",
            referrer_host="news.ycombinator.com",
            visitor=visitor,
        )
    return site


def test_requires_login(site: Site) -> None:
    assert Client().get(URL).status_code == 302


def test_summary_shows_tables(owner: Client, site: Site) -> None:
    response = owner.get(URL)
    html = response.content.decode()
    assert response.status_code == 200
    assert "사이트A" in html and "/best" in html and "news.ycombinator.com" in html
    assert '<td class="num">42</td><td class="num">7</td>' in html
    assert response.context["days"] == 7
    assert len(response.context["sites"][0]["daily"]) == 7


def test_summary_30_days_and_bad_value(owner: Client, site: Site) -> None:
    assert len(owner.get(URL, {"days": 30}).context["sites"][0]["daily"]) == 30
    assert owner.get(URL, {"days": "x"}).context["days"] == 7
    assert owner.get(URL, {"days": 5}).context["days"] == 7


def test_four_queries_per_site(owner: Client, site: Site) -> None:
    owner.get(URL)
    with CaptureQueriesContext(connection) as before:
        owner.get(URL)
    Site.objects.create(key="b", name="B", allowed_hosts="b.kr")
    with CaptureQueriesContext(connection) as after:
        owner.get(URL)
    assert len(after) - len(before) == 4


def test_site_list_links_to_summary(owner: Client, site: Site) -> None:
    assert URL in owner.get("/admin/metrics/site/").content.decode()


def test_staff_without_site_view_permission_gets_403(site: Site) -> None:
    """목록과 같은 처리: 사이트 보기 권한이 없는 staff 는 요약도 403(#43)."""
    from django.contrib.auth.models import Permission

    staff = User.objects.create_user("staff", password=None, is_staff=True)
    client = Client()
    client.force_login(staff)
    assert client.get("/admin/metrics/site/").status_code == 403
    assert client.get(URL).status_code == 403

    staff.user_permissions.add(Permission.objects.get(codename="view_site"))
    allowed = Client()
    allowed.force_login(User.objects.get(pk=staff.pk))
    assert allowed.get(URL).status_code == 200


def test_captions_name_the_site(owner: Client, site: Site) -> None:
    """낭독기로 표를 건너뛰어도 어느 사이트 표인지 안다(#53)."""
    Site.objects.create(key="b", name="사이트B", allowed_hosts="b.kr")
    captions = re.findall(r"<caption>(.*?)</caption>", owner.get(URL).content.decode())
    assert len(captions) == 6
    assert all(c.startswith("사이트A (a) — ") for c in captions[:3])
    assert all(c.startswith("사이트B (b) — ") for c in captions[3:])


def test_captions_tell_same_named_sites_apart(owner: Client, site: Site) -> None:
    """이름이 같은 두 사이트도 caption 의 키로 구분한다(#59)."""
    Site.objects.create(key="a2", name="사이트A", allowed_hosts="a2.kr")
    captions = re.findall(r"<caption>(.*?)</caption>", owner.get(URL).content.decode())
    assert len(set(captions)) == 6


def test_inactive_sites_are_left_out(owner: Client, site: Site) -> None:
    """끄기가 정리 수단이다 — 꺼진 사이트는 요약에서 빠진다(#59)."""
    Site.objects.create(key="off", name="꺼진곳", allowed_hosts="off.kr", is_active=False)
    response = owner.get(URL)
    assert [b["site"].key for b in response.context["sites"]] == ["a"]
    assert "꺼진곳" not in response.content.decode()


def test_inactive_sites_add_no_queries(owner: Client, site: Site) -> None:
    owner.get(URL)
    with CaptureQueriesContext(connection) as before:
        owner.get(URL)
    Site.objects.create(key="off", name="꺼짐", allowed_hosts="off.kr", is_active=False)
    with CaptureQueriesContext(connection) as after:
        owner.get(URL)
    assert len(after) == len(before)


def test_long_key_heading_wraps(owner: Client) -> None:
    """긴 키가 390px 에서 h2 를 넘쳐 페이지를 밀지 않는다(#59)."""
    key = "k" * 49
    Site.objects.create(key=key, name="긴키", allowed_hosts="k.kr")
    html = owner.get(URL).content.decode()
    assert f'<h2 class="site">긴키 ({key})</h2>' in html
    assert re.search(
        r"\.metrics-summary h2\.site, \.metrics-summary caption \{[^}]*overflow-wrap: anywhere",
        html,
    )
    assert ".metrics-summary caption { text-transform: none; }" in html  # 키는 소문자 그대로


def test_is_active_help_text_says_what_turning_off_does() -> None:
    help_text = str(Site._meta.get_field("is_active").help_text)
    assert "수집" in help_text and "요약" in help_text and "남" in help_text


def test_long_labels_wrap_and_counts_stay_in_number_column(owner: Client, site: Site) -> None:
    """긴 경로 하나가 표를 넓혀 숫자 열을 밀어내지 않는다(#53)."""
    long_path = "/" + "x" * 400
    PageView.objects.create(
        site=site, occurred_at=timezone.now(), path=long_path, referrer_host="", visitor="v9"
    )
    html = owner.get(URL).content.decode()
    assert f'<td class="label">{long_path}</td><td class="num">1</td>' in html
    assert "table-layout: fixed" in html and "overflow-wrap: anywhere" in html


def test_header_has_no_view_site_link(owner: Client, site: Site) -> None:
    """「사이트 보기」는 `/`(Not Found)로 가므로 없앤다(#53)."""
    response = owner.get(URL)
    assert response.context["site_url"] is None
    assert 'href="/"' not in response.content.decode()


@pytest.mark.parametrize(("days", "other"), [(7, 30), (30, 7)])
def test_current_period_is_marked_for_screen_readers(
    owner: Client, site: Site, days: int, other: int
) -> None:
    """#61: 굵은 글씨만으로는 낭독기가 현재 기간을 모른다."""
    page = owner.get(URL, {"days": days}).content.decode()
    assert re.search(rf'aria-current="page"[^>]*>최근 {days}일<', page)
    assert f'<a href="?days={other}">최근 {other}일</a>' in page
    assert not re.search(rf'aria-current="page"[^>]*>최근 {other}일<', page)
