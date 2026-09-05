"""Negative typing-regression contract for `Task` receiver-state gating.

NOT a pytest. This file is never collected by pytest (it lives outside
``tests/unit|integration|e2e`` and every function is named ``illegal_*``).
It is a static-typing contract enforced by ``zuban check --strict`` in CI.

Each function body makes exactly one transition call whose declared receiver
state does not match the task's state. Under zuban this is the static error
"Invalid self argument ..." (reported under the ``misc`` code, not a dedicated
``invalid-self-argument`` code). The trailing ``# type: ignore[misc]`` MUST
stay used: under ``--warn-unused-ignores``, an analyzer upgrade that stops
raising the error turns the ignore into an unused one and fails the build —
the executable regression alarm for the typestate gating (change
``task-static-transition-gating`` D11). Each ignore sits on a single bare
illegal call, so no other ``misc`` error can mask a regression on that line.

The six paths cover every transition method called from at least one wrong
source state, plus DONE's terminality (no transition is legal from DONE).
"""
# region MODULE_CONTRACT
# PURPOSE: Encode the six illegal Task-transition paths as static errors so an analyzer regression that disables receiver-state gating is caught by CI.
# SCOPE: Type-checking contract only; not executed by pytest.
# KEYWORDS: typing, zuban, typestate, invalid self argument, misc, negative test, regression contract
# endregion MODULE_CONTRACT

from __future__ import annotations

from yascheduler.domain.model import (
    Done,
    NodeId,
    Running,
    Task,
    TaskId,
    Todo,
)

_NODE = NodeId(1)
_ID = TaskId(1)


def _todo() -> Task[Todo]:
    return Task(task_id=_ID, engine="e", state=Todo())


def _running() -> Task[Running]:
    return Task(
        task_id=_ID,
        engine="e",
        state=Running(allocated_node_id=_NODE, remote_folder="/r"),
    )


def _done() -> Task[Done]:
    return Task(task_id=_ID, engine="e", state=Done())


# RUNNING-methods called on Task[Todo] (legal source is Running).


def illegal_complete_on_todo() -> None:
    """complete requires Task[Running]; Task[Todo] is a static error."""
    _todo().complete(local_folder="/l", remote_folder="/r")  # type: ignore[misc]


def illegal_fail_on_todo() -> None:
    """fail requires Task[Running]; Task[Todo] is a static error."""
    _todo().fail("x", local_folder="/l", remote_folder="/r")  # type: ignore[misc]


def illegal_abandon_on_todo() -> None:
    """abandon requires Task[Running]; Task[Todo] is a static error."""
    _todo().abandon()  # type: ignore[misc]


# TODO-methods called on Task[Running] (legal source is Todo).


def illegal_run_on_running() -> None:
    """run requires Task[Todo]; Task[Running] is a static error."""
    _running().run(_NODE, "/r")  # type: ignore[misc]


def illegal_reject_on_running() -> None:
    """reject requires Task[Todo]; Task[Running] is a static error."""
    _running().reject("x")  # type: ignore[misc]


# DONE is terminal: no transition is legal from Task[Done].


def illegal_complete_on_done() -> None:
    """DONE is terminal; complete on Task[Done] is a static error."""
    _done().complete(local_folder="/l", remote_folder="/r")  # type: ignore[misc]
