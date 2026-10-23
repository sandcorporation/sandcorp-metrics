"""사이트 만들기·고치기(MCP가 부른다). 검증은 모델 `full_clean`과 같다."""

from django.core.exceptions import ValidationError

from metrics.models import Site


class SiteError(Exception):
    """호출한 쪽이 읽을 사이트 규칙 위반."""


def _save(site: Site) -> Site:
    try:
        site.full_clean()
    except ValidationError as exc:
        raise SiteError(
            "; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())
        ) from exc
    site.save()
    return site


def create_site(key: str, name: str, allowed_hosts: str) -> Site:
    return _save(Site(key=key, name=name, allowed_hosts=allowed_hosts))


def update_site(
    key: str, *, name: str | None, allowed_hosts: str | None, is_active: bool | None
) -> Site:
    site = Site.objects.filter(key=key).first()
    if site is None:
        raise SiteError(f"unknown site: {key}")
    if name is not None:
        site.name = name
    if allowed_hosts is not None:
        site.allowed_hosts = allowed_hosts
    if is_active is not None:
        site.is_active = is_active
    return _save(site)
