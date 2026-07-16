"""Pure closure binding conn + adapter.quote into an OuterRunCallable for adapter.get_cpu_cores / setup_node."""
# region MODULE_CONTRACT
# PURPOSE: Produce an OuterRunCallable with pre-bound conn and quote for adapter methods that need a run callable.
# SCOPE: make_run_fn factory — pure closure, no side effects.
# KEYWORDS: run_fn, closure, OuterRunCallable, make_run_fn
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncssh.connection import SSHClientConnection
    from asyncssh.process import SSHCompletedProcess

    from .adapters import RemoteMachineAdapter
    from .protocol import OuterRunCallable

__all__ = ["make_run_fn"]


# region FUNC_make_run_fn
# PURPOSE: Build OuterRunCallable with pre-bound conn and adapter.quote.
def make_run_fn(
    conn: SSHClientConnection,
    adapter: RemoteMachineAdapter,
) -> OuterRunCallable:
    """Build OuterRunCallable with pre-bound conn and quote."""

    async def _run_fn(
        *args: object,
        cwd: str | None = None,
        **kwargs: dict[str, Any],
    ) -> SSHCompletedProcess:
        return await adapter.run(
            conn,
            adapter.quote,
            str(args[0]) if args else "",
            *args[1:],
            cwd=cwd,
            **kwargs,
        )

    return _run_fn


# endregion FUNC_make_run_fn
