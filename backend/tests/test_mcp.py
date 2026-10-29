"""MCP `/mcp`: tools/list 7개, 도구마다 1건, admin 스코프 없으면 거부."""

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from sandcorp_authkit.testing import OWNER_SUB

from metrics.models import PageView, Site
from tests.conftest import TokenSigner

pytestmark = pytest.mark.django_db
TOOL_NAMES = {
    "whoami",
    "list_sites",
    "create_site",
    "update_site",
    "site_stats",
    "top_paths",
    "top_referrers",
}


def rpc(token_signer: TokenSigner, method: str, params: dict[str, object] | None = None) -> dict:  # type: ignore[type-arg]
    response = Client().post(
        "/mcp",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}),
        content_type="application/json",
        headers=token_signer.bearer(),
    )
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def call(token_signer: TokenSigner, tool_name: str, /, **arguments: object) -> dict:  # type: ignore[type-arg]
    answer = rpc(token_signer, "tools/call", {"name": tool_name, "arguments": arguments})
    return answer["result"]  # type: ignore[no-any-return]


@pytest.fixture
def site() -> Site:
    site = Site.objects.create(key="a", name="A", allowed_hosts="a.kr")
    for i, (path, ref) in enumerate([("/x", "t.co"), ("/x", ""), ("/y", "t.co")]):
        PageView.objects.create(
            site=site,
            occurred_at=timezone.now() - timedelta(minutes=i),
            path=path,
            referrer_host=ref,
            visitor=f"v{i}",
        )
    return site


def test_initialize_and_tools_list(token_signer: TokenSigner) -> None:
    init = rpc(token_signer, "initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert init["serverInfo"]["name"] == "sandcorp-metrics" and init["instructions"]
    tools = rpc(token_signer, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == TOOL_NAMES


def test_whoami(token_signer: TokenSigner) -> None:
    result = call(token_signer, "whoami")
    assert result["structuredContent"]["sub"] == OWNER_SUB


def test_create_update_and_list_sites(token_signer: TokenSigner, site: Site) -> None:
    created = call(token_signer, "create_site", key="b", name="B", allowed_hosts="B.kr, www.b.kr")
    assert created["structuredContent"]["allowed_hosts"] == ["b.kr", "www.b.kr"]
    updated = call(token_signer, "update_site", key="b", is_active=False)
    assert updated["structuredContent"]["is_active"] is False
    listed = call(token_signer, "list_sites")["structuredContent"]["sites"]
    assert [s["key"] for s in listed] == ["a", "b"]
    assert listed[0]["numbers"]["today_pageviews"] == 3


def test_site_errors_are_tool_errors(token_signer: TokenSigner, site: Site) -> None:
    assert call(token_signer, "create_site", key="a", name="x", allowed_hosts="x.kr")["isError"]
    assert call(token_signer, "create_site", key="bad key", name="x", allowed_hosts="x")["isError"]
    assert call(token_signer, "update_site", key="zzz", name="x")["isError"]
    assert call(token_signer, "site_stats", key="zzz")["isError"]
    assert call(token_signer, "site_stats", key="a", days=0)["isError"]


def test_site_stats(token_signer: TokenSigner, site: Site) -> None:
    result = call(token_signer, "site_stats", key="a", days=7)["structuredContent"]
    assert result["days"] == 7 and len(result["daily"]) == 7
    assert result["daily"][-1]["pageviews"] == 3
    assert result["summary"]["today_visitors"] == 3


def test_top_paths_and_referrers(token_signer: TokenSigner, site: Site) -> None:
    paths = call(token_signer, "top_paths", key="a")["structuredContent"]["rows"]
    assert paths == [{"path": "/x", "pageviews": 2}, {"path": "/y", "pageviews": 1}]
    refs = call(token_signer, "top_referrers", key="a", limit=5)["structuredContent"]["rows"]
    assert refs == [{"referrer": "t.co", "pageviews": 2}]


def test_without_admin_scope_is_refused(token_signer: TokenSigner) -> None:
    response = Client().post(
        "/mcp",
        "{}",
        content_type="application/json",
        headers=token_signer.bearer(scope="login"),
    )
    assert response.status_code == 403
    assert Client().post("/mcp", "{}", content_type="application/json").status_code == 401
