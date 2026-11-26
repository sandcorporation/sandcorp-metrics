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
    assert all(c.startswith("사이트A — ") for c in captions[:3])
    assert all(c.startswith("사이트B — ") for c in captions[3:])


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
