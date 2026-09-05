# region MODULE_CONTRACT
# PURPOSE: Unit tests for _run_apt_with_retry transient apt-failure handling.
# SCOPE: _run_apt_with_retry against a fake OuterRunCallable emitting ProcessError or success.
# KEYWORDS: apt, retry, transient, exit 100, setup_node, regression
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from asyncssh.process import ProcessError

from yascheduler.infra.ssh.platform import linux as linux_mod
from yascheduler.infra.ssh.platform.linux import _run_apt_with_retry

if TYPE_CHECKING:
    from collections.abc import Sequence


def _proc_error(exit_status: int) -> ProcessError:
    return ProcessError(
        env=None,
        command="apt-get update",
        subsystem=None,
        exit_status=exit_status,
        exit_signal=None,
        returncode=exit_status,
        stdout=b"",
        stderr=b"",
    )


class _FakeRun:
    """Records calls; raises ProcessError per a scripted list of exit statuses."""

    def __init__(self, exits: Sequence[int | None]) -> None:
        # None means "success" for that call.
        self._exits = list(exits)
        self.calls: list[str] = []

    async def __call__(self, *args: object, **kwargs: Any) -> Any:
        self.calls.append(str(args[0]) if args else "")
        if not self._exits:
            return None
        nxt = self._exits.pop(0)
        if nxt is None:
            return None
        raise _proc_error(nxt)


async def _asyncio_sleep_nop(_delay: float) -> None:
    return


async def test_retries_on_exit_100_then_succeeds(monkeypatch: Any) -> None:
    """Exit 100 on first attempt, success on second: command retried, no raise."""
    monkeypatch.setattr(linux_mod.asyncio, "sleep", _asyncio_sleep_nop)
    fake = _FakeRun([100, None])

    await _run_apt_with_retry(fake, "apt-get update", attempts=3)

    assert len(fake.calls) == 2


async def test_raises_after_exhausting_attempts(monkeypatch: Any) -> None:
    """Persistent exit 100 exhausts attempts and re-raises last ProcessError."""
    monkeypatch.setattr(linux_mod.asyncio, "sleep", _asyncio_sleep_nop)
    fake = _FakeRun([100, 100, 100])

    try:
        await _run_apt_with_retry(fake, "apt-get update", attempts=3)
    except ProcessError as exc:
        assert exc.exit_status == 100
    else:
        raise AssertionError("expected ProcessError")
    assert len(fake.calls) == 3


async def test_non_100_exit_propagates_immediately(monkeypatch: Any) -> None:
    """Non-transient exit (e.g. 1) is raised immediately, not retried."""
    monkeypatch.setattr(linux_mod.asyncio, "sleep", _asyncio_sleep_nop)
    fake = _FakeRun([1])

    try:
        await _run_apt_with_retry(fake, "apt-get install -y foo", attempts=3)
    except ProcessError as exc:
        assert exc.exit_status == 1
    else:
        raise AssertionError("expected ProcessError")
    assert len(fake.calls) == 1
