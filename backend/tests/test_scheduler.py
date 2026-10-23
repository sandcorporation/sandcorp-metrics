import pytest
from django.core.management import call_command

from services import scheduler


def test_commands_starts_empty() -> None:
    assert scheduler.COMMANDS == ()


def test_run_cycle_calls_in_order_and_keeps_going_after_a_failure() -> None:
    called: list[str] = []

    def call(name: str) -> None:
        called.append(name)
        if name == "b":
            raise RuntimeError("boom")

    assert scheduler.run_cycle(("a", "b", "c"), call) == {"a": True, "b": False, "c": True}
    assert called == ["a", "b", "c"]


def test_run_scheduler_once_runs_the_command_list(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(scheduler, "COMMANDS", ("check",))
    monkeypatch.setattr(scheduler, "call_command", lambda name: called.append(name))

    call_command("run_scheduler", "--once")

    assert called == ["check"]
