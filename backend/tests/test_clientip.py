"""클라이언트 IP: X-Forwarded-For 오른쪽에서 PROXY_HOPS번째(왼쪽은 위조 가능)."""

from django.test import RequestFactory
from pytest_django.fixtures import Settings

from core.clientip import client_ip


def test_one_hop_takes_rightmost(settings: Settings) -> None:
    settings.PROXY_HOPS = 1
    assert (
        client_ip(RequestFactory().get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 1.2.3.4")) == "1.2.3.4"
    )


def test_two_hops_takes_second_from_right(settings: Settings) -> None:
    settings.PROXY_HOPS = 2
    req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 1.2.3.4, 10.0.0.2")
    assert client_ip(req) == "1.2.3.4"


def test_short_header_falls_back_to_remote_addr(settings: Settings) -> None:
    settings.PROXY_HOPS = 2
    req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="172.17.0.1")
    assert client_ip(req) == "172.17.0.1"


def test_no_header_or_zero_hops_uses_remote_addr(settings: Settings) -> None:
    settings.PROXY_HOPS = 1
    assert client_ip(RequestFactory().get("/", REMOTE_ADDR="9.9.9.9")) == "9.9.9.9"
    settings.PROXY_HOPS = 0
    req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="9.9.9.9")
    assert client_ip(req) == "9.9.9.9"
