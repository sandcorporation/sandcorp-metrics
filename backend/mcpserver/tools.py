"""MCP 도구: `services/`를 감싼 얇은 껍데기. 입력을 검증하고 출력 모양을 만든다.

`@tool(이름, 제목, 설명, 입력 모델)`로 `(token, args) -> dict` 함수를 등록한다(쓰기 도구는
`read_only=False`). 입력 모델(pydantic, `extra="forbid"`)이 `inputSchema`가 되고, 읽는 쪽이 봐야
할 실패는 `ToolError`(→ `isError` 결과)로 낸다. 모든 도구는 `/mcp`의 bearer 검사(스코프 admin)
뒤에서 돈다. 본보기: portfolio `backend/mcpserver/tools.py`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Protocol

from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field

from core.schemas import SiteReport, daily_items, numbers, site_numbers
from metrics.models import Site
from oauth.tokens import AccessToken
from services import report, sites
from services.stats import site_summary

type JSON = str | int | float | bool | None | list[JSON] | dict[str, JSON]
type ToolResult = dict[str, JSON]


class ToolError(Exception):
    """도구 수준의 실패. 메시지가 MCP 클라이언트에 그대로 보인다."""


class RegisteredTool(Protocol):
    @property
    def name(self) -> str: ...

    def definition(self) -> dict[str, JSON]: ...

    def call(self, token: AccessToken, arguments: dict[str, JSON]) -> ToolResult: ...


@dataclass(frozen=True)
class Tool[M: BaseModel]:
    name: str
    title: str
    description: str
    input_model: type[M]
    handler: Callable[[AccessToken, M], ToolResult]
    read_only: bool = True

    def definition(self) -> dict[str, JSON]:
        schema: dict[str, JSON] = self.input_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": schema,
            "annotations": {"readOnlyHint": self.read_only},
        }

    def call(self, token: AccessToken, arguments: dict[str, JSON]) -> ToolResult:
        return self.handler(token, self.input_model.model_validate(arguments))


TOOLS: dict[str, RegisteredTool] = {}


def tool[M: BaseModel](
    name: str, title: str, description: str, input_model: type[M], *, read_only: bool = True
) -> Callable[[Callable[[AccessToken, M], ToolResult]], Callable[[AccessToken, M], ToolResult]]:
    def register(
        handler: Callable[[AccessToken, M], ToolResult],
    ) -> Callable[[AccessToken, M], ToolResult]:
        if name in TOOLS:
            raise ValueError(f"MCP tool {name!r} is registered twice")
        TOOLS[name] = Tool(name, title, description, input_model, handler, read_only)
        return handler

    return register


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoInput(Strict):
    pass


class SiteKey(Strict):
    key: str


class SiteDays(Strict):
    key: str
    days: Annotated[int, Field(ge=1, le=report.MAX_DAYS)] = 30


class TopInput(Strict):
    key: str
    days: Annotated[int, Field(ge=1, le=report.MAX_DAYS)] = 7
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class CreateSite(Strict):
    key: str = Field(description="slug (letters, digits, - _). Goes in the snippet's data-site.")
    name: str
    allowed_hosts: str = Field(description="comma-separated hosts, e.g. 'a.kr,www.a.kr'")


class UpdateSite(Strict):
    key: str
    name: str | None = None
    allowed_hosts: str | None = None
    is_active: bool | None = None


def _site(key: str) -> Site:
    site = Site.objects.filter(key=key).first()
    if site is None:
        raise ToolError(f"unknown site: {key}")
    return site


def _site_json(site: Site) -> dict[str, JSON]:
    return {
        "key": site.key,
        "name": site.name,
        "allowed_hosts": [host for host in sorted(site.host_set())],
        "is_active": site.is_active,
    }


@tool("whoami", "Who am I", "The identity this connection acts as.", NoInput)
def whoami(token: AccessToken, args: NoInput) -> ToolResult:
    return {
        "sub": token.sub,
        "client_id": token.client_id,
        "scopes": [scope for scope in sorted(token.scopes)],
        "expires_at": token.exp,
    }


@tool(
    "list_sites",
    "List sites",
    "Every site (also inactive ones) with its allowed hosts and today's numbers.",
    NoInput,
)
def list_sites(token: AccessToken, args: NoInput) -> ToolResult:
    now = timezone.now()
    items: list[JSON] = []
    for site in Site.objects.all():
        item = _site_json(site)
        item["numbers"] = site_numbers(site, site_summary(site, now)).model_dump(mode="json")
        items.append(item)
    return {"sites": items}


@tool(
    "create_site",
    "Create a site",
    "Register a site to measure. Then put <script src='https://metrics.sandcorp.co.kr/m.js' "
    "data-site='KEY' defer></script> on its pages. Views from other hosts are dropped.",
    CreateSite,
    read_only=False,
)
def create_site(token: AccessToken, args: CreateSite) -> ToolResult:
    try:
        site = sites.create_site(args.key, args.name, args.allowed_hosts)
    except sites.SiteError as exc:
        raise ToolError(str(exc)) from exc
    return _site_json(site)


@tool(
    "update_site",
    "Update a site",
    "Change a site's name, allowed hosts or on/off (turning it off stops collecting and hides it "
    "from the public numbers). Only the given fields change.",
    UpdateSite,
    read_only=False,
)
def update_site(token: AccessToken, args: UpdateSite) -> ToolResult:
    try:
        site = sites.update_site(
            args.key, name=args.name, allowed_hosts=args.allowed_hosts, is_active=args.is_active
        )
    except sites.SiteError as exc:
        raise ToolError(str(exc)) from exc
    return _site_json(site)


@tool(
    "site_stats",
    "Site stats",
    "Summary numbers plus one row per day (oldest first, today live) for the last `days` days.",
    SiteDays,
)
def site_stats(token: AccessToken, args: SiteDays) -> ToolResult:
    now = timezone.now()
    site = _site(args.key)
    result = SiteReport(
        key=site.key,
        name=site.name,
        days=args.days,
        summary=numbers(site_summary(site, now)),
        daily=daily_items(report.daily_rows(site, args.days, now)),
    )
    return result.model_dump(mode="json")


def _top(rows: list[report.TopRow], label: str) -> ToolResult:
    return {"rows": [{label: row.label, "pageviews": row.count} for row in rows]}


@tool("top_paths", "Top paths", "Most viewed paths in the last `days` days.", TopInput)
def top_paths(token: AccessToken, args: TopInput) -> ToolResult:
    site = _site(args.key)
    return _top(report.top_paths(site, args.days, args.limit, timezone.now()), "path")


@tool(
    "top_referrers",
    "Top referrers",
    "Referrer hosts with the most views in the last `days` days (direct and same-site views "
    "have no referrer and are left out).",
    TopInput,
)
def top_referrers(token: AccessToken, args: TopInput) -> ToolResult:
    site = _site(args.key)
    return _top(report.top_referrers(site, args.days, args.limit, timezone.now()), "referrer")
