import pytest
from django.db import connection
from django.db.utils import OperationalError
from django.test import Client


@pytest.mark.django_db
def test_health_reports_database_reachable(client: Client) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


@pytest.mark.django_db
def test_health_reports_unavailable_when_database_is_down(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise OperationalError("connection refused")

    monkeypatch.setattr(connection, "cursor", refuse)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "unavailable"}


@pytest.mark.django_db
def test_health_gives_503_within_connect_timeout_when_database_never_answers(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TCP는 받지만 응답하지 않는 DB: 연결 시간 한도(#44) 안에 503을 준다."""
    import socket
    import time

    from django.conf import settings
    from django.db.backends.mysql.base import DatabaseWrapper

    import core.api

    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        params = dict(settings.DATABASES["default"])
        params.update(HOST="127.0.0.1", PORT=str(silent.getsockname()[1]))
        configured = settings.DATABASES["default"]["OPTIONS"]
        assert isinstance(configured, dict)
        options = dict(configured)
        options["connect_timeout"] = 1
        params["OPTIONS"] = options
        unreachable = DatabaseWrapper(params)
        monkeypatch.setattr(core.api, "connection", unreachable)

        started = time.monotonic()
        response = client.get("/api/health")
        elapsed = time.monotonic() - started
        unreachable.close()

    assert response.status_code == 503
    assert elapsed < 3
