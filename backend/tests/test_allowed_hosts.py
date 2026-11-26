"""허용 호스트 형식(#42): 스킴·경로 등은 admin 폼 오류·MCP isError, 공백·대문자·포트는 받는다."""

import pytest
from django.contrib.auth.models import User
from django.test import Client

from metrics.models import Site
from services.sites import SiteError, create_site, update_site
from tests.conftest import TokenSigner
from tests.test_mcp import call

pytestmark = pytest.mark.django_db

BAD = [
    "https://a.example",
    "a.example/x",
    "a.example/",
    "user@a.example",
    "a.kr,,b.kr",
    "a.kr, ",
    "a..kr",
    "-a.kr",
    "a.kr:http",
    "a.kr:",
    "a kr",
    "한글.kr",
]


@pytest.mark.parametrize("value", BAD)
def test_rejects_non_host_values_and_names_the_bad_piece(value: str) -> None:
    with pytest.raises(SiteError) as caught:
        create_site("s", "S", value)
    assert "allowed_hosts" in str(caught.value)
    assert not Site.objects.filter(key="s").exists()


def test_message_names_the_bad_piece() -> None:
    with pytest.raises(SiteError, match="https://a.example"):
        create_site("s", "S", "b.kr, https://a.example")


def test_accepts_spaces_case_ports_and_localhost() -> None:
    site = create_site("s", "S", " A.kr , www.a.kr:8080,localhost,127.0.0.1 ")
    assert site.host_set() == frozenset({"a.kr", "www.a.kr", "localhost", "127.0.0.1"})


def test_update_rejects_bad_hosts() -> None:
    create_site("s", "S", "a.kr")
    with pytest.raises(SiteError):
        update_site("s", name=None, allowed_hosts="a.kr/x", is_active=None)
    assert Site.objects.get(key="s").allowed_hosts == "a.kr"


def test_existing_bad_rows_still_load_and_other_fields_can_change() -> None:
    """기존 행은 마이그레이션으로 바꾸지 않는다 — 읽기는 그대로, 고칠 때만 검증."""
    Site.objects.create(key="old", name="O", allowed_hosts="https://a.kr")
    assert Site.objects.get(key="old").host_set() == frozenset({"https"})


def test_mcp_create_site_is_tool_error_with_reason(token_signer: TokenSigner) -> None:
    result = call(token_signer, "create_site", key="s", name="S", allowed_hosts="https://a.kr")
    assert result["isError"]
    assert "https://a.kr" in json_text(result)


def test_admin_form_shows_field_error() -> None:
    client = Client()
    client.force_login(User.objects.create_superuser("owner", password=None))
    response = client.post(
        "/admin/metrics/site/add/",
        {"key": "s", "name": "S", "allowed_hosts": "a.kr/x", "is_active": "on"},
    )
    assert response.status_code == 200
    assert "a.kr/x" in " ".join(response.context["adminform"].form.errors["allowed_hosts"])
    assert not Site.objects.filter(key="s").exists()


def json_text(result: dict) -> str:  # type: ignore[type-arg]
    return " ".join(str(c.get("text", "")) for c in result.get("content", []))
