"""admin 사이트 삭제는 열지 않는다(#47): 정리는 끄기(`is_active=False`)."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from metrics.models import DailyStat, Site

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner() -> Client:
    client = Client()
    client.force_login(User.objects.create_superuser("owner", password=None))
    return client


@pytest.fixture
def site() -> Site:
    site = Site.objects.create(key="a", name="A", allowed_hosts="a.kr")
    DailyStat.objects.create(site=site, date=timezone.localdate(), pageviews=1, visitors=1)
    return site


def test_change_page_has_no_delete_link(owner: Client, site: Site) -> None:
    response = owner.get(f"/admin/metrics/site/{site.pk}/change/")
    assert response.status_code == 200
    assert "/delete/" not in response.content.decode()


def test_changelist_has_no_delete_selected_action(owner: Client, site: Site) -> None:
    response = owner.get("/admin/metrics/site/")
    assert response.status_code == 200
    assert "delete_selected" not in response.content.decode()
    bulk = owner.post(
        "/admin/metrics/site/", {"action": "delete_selected", "_selected_action": [site.pk]}
    )
    assert bulk.status_code in (200, 302)
    assert Site.objects.filter(pk=site.pk).exists()


def test_delete_url_is_forbidden(owner: Client, site: Site) -> None:
    assert owner.get(f"/admin/metrics/site/{site.pk}/delete/").status_code == 403
    assert owner.post(f"/admin/metrics/site/{site.pk}/delete/", {"post": "yes"}).status_code == 403
    assert Site.objects.filter(pk=site.pk).exists()


def test_turning_off_hides_site_from_public_numbers(owner: Client, site: Site) -> None:
    response = owner.post(
        f"/admin/metrics/site/{site.pk}/change/",
        {"key": "a", "name": "A", "allowed_hosts": "a.kr"},  # is_active 체크 해제
    )
    assert response.status_code == 302
    assert Client().get("/api/sites/a/stats").status_code == 404
    assert Client().get("/api/stats").json()["sites"] == []


def test_key_is_read_only_on_existing_site(owner: Client, site: Site) -> None:
    """#61: 키를 바꾸면 붙여 둔 스니펫의 조회가 버려진다 — 만든 뒤엔 읽기 전용."""
    page = owner.get(f"/admin/metrics/site/{site.pk}/change/").content.decode()
    assert 'name="key"' not in page
    assert "만든 뒤 바꿀 수 없다" in page
    owner.post(
        f"/admin/metrics/site/{site.pk}/change/",
        {"key": "b", "name": "A2", "allowed_hosts": "a.kr", "is_active": "on"},
    )
    site.refresh_from_db()
    assert (site.key, site.name) == ("a", "A2")


def test_key_is_entered_when_adding(owner: Client) -> None:
    page = owner.get("/admin/metrics/site/add/").content.decode()
    assert 'name="key"' in page
    assert "만든 뒤 바꿀 수 없다" in page
    owner.post(
        "/admin/metrics/site/add/",
        {"key": "new", "name": "N", "allowed_hosts": "n.kr", "is_active": "on"},
    )
    assert Site.objects.filter(key="new").exists()


def test_changelist_hosts_can_break_after_commas(owner: Client) -> None:
    """#61: 390px에서 긴 허용 호스트가 이름 열을 한 글자 폭으로 밀지 않게."""
    Site.objects.create(key="b", name="B", allowed_hosts="b.kr,www.b.kr,<x>.kr")
    page = owner.get("/admin/metrics/site/").content.decode()
    assert "b.kr,<wbr>www.b.kr,<wbr>&lt;x&gt;.kr" in page
    assert "td.field-hosts { overflow-wrap: anywhere" in page
