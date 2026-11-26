"""경로 마스킹: 순수 함수 표, collect 저장·5초 중복, 기존 행 일괄 적용 명령."""

import io
from datetime import UTC, datetime

import pytest
from django.core.management import call_command

from metrics.models import PageView, Site
from services.collect import normalize_path, record
from services.paths import mask_path

UUID = "123e4567-e89b-12d3-a456-426614174000"
HEX32 = "3f9a" * 8
CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"
NOW = datetime(2026, 10, 23, 3, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/join/Ab3dE9fG", "/join/*"),
        ("/JOIN/abc", "/JOIN/*"),
        ("/reset/x", "/reset/*"),
        ("/verify/x", "/verify/*"),
        ("/confirm/x", "/confirm/*"),
        ("/join", "/join"),
        (f"/invite/{HEX32}", "/invite/*"),
        ("/a/openai-decisions-api-launch", "/a/openai-decisions-api-launch"),
        ("/work/codemit", "/work/codemit"),
        ("/p/2_xuwAZeXXSvtbBXuuNr1A", "/p/*"),
        ("/blog/2026-10-23-first-post", "/blog/2026-10-23-first-post"),
        ("/blog/2026-10-23-1234567890", "/blog/*"),
        # 날짜 + 글자 단어 하나(#45)
        ("/blog/2026-11-26-launching", "/blog/2026-11-26-launching"),
        ("/blog/20261126-launching", "/blog/20261126-launching"),
        ("/blog/launching-2026-11-26", "/blog/launching-2026-11-26"),
        ("/blog/2026-11-launching-notes", "/blog/2026-11-launching-notes"),
        ("/blog/2026-11-26-출시", "/blog/2026-11-26-출시"),
        ("/blog/2026-13-26-launching", "/blog/*"),
        ("/blog/2026-11-26-launch2", "/blog/*"),
        ("/blog/2026-11-26-1234-launching", "/blog/*"),
        ("/blog/20261126", "/blog/*"),
        ("/blog/2026-11-26", "/blog/2026-11-26"),
        ("/join/2026-11-26-launching", "/join/*"),
        ("/t/deadbeef-2026-11-26", "/t/*"),
        ("/t/aB3dE9fGhIjK-2026-11-26", "/t/*"),
        (f"/u/{UUID}/edit", "/u/*/edit"),
        ("/o/123456", "/o/*"),
        ("/o/12345", "/o/12345"),
        ("/c/deadbeef", "/c/*"),
        ("/c/deadbee", "/c/deadbee"),
        ("/글/한글-제목-입니다", "/글/한글-제목-입니다"),
        ("/", "/"),
        ("/a/b/", "/a/b/"),
        ("/join/*", "/join/*"),
    ],
)
def test_mask_path_table(path: str, expected: str) -> None:
    assert mask_path(path) == expected


def test_mask_is_idempotent() -> None:
    once = mask_path(f"/invite/{HEX32}/x/{UUID}")
    assert mask_path(once) == once


def test_normalize_masks_then_truncates() -> None:
    assert normalize_path("https://t.example/join/Ab3dE9fG?x=1") == "/join/*"
    assert normalize_path("https://t.example/" + "x" * 600) == "/" + "x" * 511


HAN = "%ED%95%9C"  # 「한」


@pytest.mark.parametrize(
    ("url_path", "expected"),
    [
        (f"/{HAN}%EA%B8%80/%EC%A0%9C%EB%AA%A9", "/한글/제목"),
        ("/%6Aoin/Ab3dE9fG", "/join/*"),
        ("/%4A%4F%49%4E/x", "/JOIN/*"),
        ("/join%2FAb3dE9fG", "/join/*"),
        ("/a%2F%2Fb", "/a//b"),
        ("/%ZZ/x", "/%ZZ/x"),
        ("/a%", "/a%"),
        ("/a%FFb", "/a\ufffdb"),
        (f"/a{HAN[:6]}", "/a\ufffd"),
        ("/a%00b%0Ac%7F%C2%85d", "/abcd"),
        ("/a\ud800b", "/ab"),
        ("/%2525", "/%25"),
    ],
)
def test_normalize_decodes_before_masking(url_path: str, expected: str) -> None:
    assert normalize_path(f"https://t.example{url_path}") == expected


@pytest.mark.parametrize(
    ("url_path", "expected"),
    [
        ("/join/%2FAb3dE9fG", "/join/*"),
        ("/join/Ab%2F3dE9fG", "/join/*"),
        ("/join/Ab3dE9fG%2F", "/join/*"),
        ("/join/Ab%2f3dE9fG/x", "/join/*/x"),
        ("/join/%2F%2FAb3dE9fG/x", "/join/*/x"),
        ("/join%2F/Ab3dE9fG", "/join//*"),
        ("/x%2Fjoin/Ab3dE9fG", "/x/join/*"),
        ("/a%2Fjoin%2FAb3dE9fG%2Fb", "/a/join/*/b"),
        ("/join//Ab3dE9fG", "/join//*"),
    ],
)
def test_normalize_splits_segments_on_encoded_slashes_only(url_path: str, expected: str) -> None:
    """조각 경계는 원래 경로의 `/`만 — 디코딩된 `/`가 비밀 조각을 둘로 가르지 않는다."""
    assert normalize_path(f"https://t.example{url_path}") == expected


def test_normalize_truncates_decoded_characters() -> None:
    assert normalize_path("https://t.example/" + HAN * 600) == "/" + "한" * 511


@pytest.fixture
def site() -> Site:
    return Site.objects.create(key="t", name="시험", allowed_hosts="t.example")


def payload(path: str, referrer: str = "") -> dict[str, str]:
    return {"s": "t", "u": f"https://t.example{path}", "r": referrer}


@pytest.mark.django_db
def test_collect_stores_masked_path_and_keeps_referrer_host(site: Site) -> None:
    assert record(
        payload("/join/Ab3dE9fG", "https://ref.example/join/Ab3dE9fG"), "1.2.3.4", CHROME, NOW
    )
    view = PageView.objects.get()
    assert (view.path, view.referrer_host) == ("/join/*", "ref.example")


@pytest.mark.django_db
def test_collect_stores_decoded_path(site: Site) -> None:
    assert record(payload(f"/{HAN}/%6Aoin/Ab3dE9fG"), "1.2.3.4", CHROME, NOW)
    assert PageView.objects.get().path == "/한/join/*"


@pytest.mark.django_db
def test_dedup_compares_masked_path(site: Site) -> None:
    assert record(payload("/join/Ab3dE9fG"), "1.2.3.4", CHROME, NOW)
    assert not record(payload("/join/Zz9yX8wV"), "1.2.3.4", CHROME, NOW)
    assert PageView.objects.count() == 1


@pytest.mark.django_db
def test_mask_existing_paths_command_is_idempotent(site: Site) -> None:
    for path in ("/join/Ab3dE9fG", "/a/openai-decisions-api-launch", f"/invite/{HEX32}"):
        PageView.objects.create(site=site, occurred_at=NOW, path=path, visitor="v")
    out = io.StringIO()
    call_command("mask_existing_paths", stdout=out)
    assert "2건" in out.getvalue()
    assert sorted(PageView.objects.values_list("path", flat=True)) == [
        "/a/openai-decisions-api-launch",
        "/invite/*",
        "/join/*",
    ]
    again = io.StringIO()
    call_command("mask_existing_paths", stdout=again)
    assert "0건" in again.getvalue()
