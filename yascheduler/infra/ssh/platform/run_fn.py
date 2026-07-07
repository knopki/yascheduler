# FILE: yascheduler/infra/ssh/platform/run_fn.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Pure closure binding conn + adapter.quote into an OuterRunCallable for adapter.get_cpu_cores / setup_node.
#   SCOPE: make_run_fn factory.
#   DEPENDS: M-PLATFORM-PROTOCOL
#   LINKS: M-PLATFORM-PROTOCOL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   make_run_fn - Build OuterRunCallable with pre-bound conn and adapter.quote.
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from gateway._make_run_fn; renamed to public make_run_fn, behavior unchanged. Both repository.connect and operations.base now import it from here instead of through the gateway class.
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncssh.connection import SSHClientConnection
    from asyncssh.process import SSHCompletedProcess

    from .adapters import RemoteMachineAdapter
    from .protocol import OuterRunCallable


# START_CONTRACT: make_run_fn
#   PURPOSE: Build OuterRunCallable with pre-bound conn and adapter.quote.
#   INPUTS: { conn: SSHClientConnection, adapter: RemoteMachineAdapter }
#   OUTPUTS: { OuterRunCallable - async callable bound to conn + adapter.quote }
#   SIDE_EFFECTS: None — pure closure.
#   LINKS: M-PLATFORM-PROTOCOL
# END_CONTRACT: make_run_fn
def make_run_fn(
    conn: SSHClientConnection, adapter: RemoteMachineAdapter
) -> OuterRunCallable:
    """Build OuterRunCallable with pre-bound conn and quote."""

    async def _run_fn(
        *args: object,
        cwd: str | None = None,
        **kwargs: Any,  # noqa: ANN401
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
