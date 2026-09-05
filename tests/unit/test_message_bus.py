# region MODULE_CONTRACT
# PURPOSE: Unit tests for the MessageBus event dispatcher.
# SCOPE: register, dispatch, multiple handlers, partial-wrapped handlers.
# KEYWORDS: MessageBus, dispatch, handler registration, partial handlers
# endregion MODULE_CONTRACT

from __future__ import annotations

import functools
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from yascheduler.application.message_bus import MessageBus
from yascheduler.domain.events import (
    DomainEvent,
    TaskCreated,
    TaskFailed,
)
from yascheduler.domain.model import Task, TaskId, Todo

if TYPE_CHECKING:
    from yascheduler.shared import Self


class TestMessageBus:
    async def test_dispatch_calls_registered_handler(self) -> None:
        bus = MessageBus()
        received: list[object] = []

        async def on_created(event: object) -> None:
            received.append(event)

        bus.register(TaskCreated, on_created)
        event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="cp2k",
        )
        await bus.dispatch([event])
        assert received == [event]

    async def test_dispatch_with_no_handlers(self) -> None:
        bus = MessageBus()
        event = TaskFailed(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            reason="err",
        )
        await bus.dispatch([event])  # no error raised

    async def test_multiple_handlers_per_event_type(self) -> None:
        bus = MessageBus()
        log_a: list[object] = []
        log_b: list[object] = []

        async def handler_a(event: object) -> None:
            log_a.append(event)

        async def handler_b(event: object) -> None:
            log_b.append(event)

        bus.register(TaskCreated, handler_a)
        bus.register(TaskCreated, handler_b)
        event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="cp2k",
        )
        await bus.dispatch([event])
        assert log_a == [event]
        assert log_b == [event]

    async def test_partial_handler_receives_event(self) -> None:
        bus = MessageBus()
        results: list[tuple[object, str]] = []

        async def handler(event: object, *, label: str) -> None:
            results.append((event, label))

        bus.register(TaskCreated, functools.partial(handler, label="test"))
        event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="cp2k",
        )
        await bus.dispatch([event])
        assert results == [(event, "test")]

    async def test_handler_failure_does_not_prevent_others(self) -> None:
        """A failing handler must not prevent subsequent handlers from running."""
        bus = MessageBus()
        results: list[TaskId] = []

        async def handler_a(event: DomainEvent) -> None:
            raise RuntimeError("handler A failed")

        async def handler_b(event: DomainEvent) -> None:
            results.append(event.task_id)

        bus.register(TaskCreated, handler_a)
        bus.register(TaskCreated, handler_b)

        event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="vasp",
        )
        await bus.dispatch([event])

        assert results == [TaskId(1)]


class TestUoWEventDispatch:
    """Tests verifying UoW event dispatch flow via MessageBus."""

    async def test_commit_dispatches_events_via_bus(self) -> None:
        """Commit calls publish_events which dispatches via bus."""
        bus = MessageBus()
        dispatched: list[object] = []

        async def on_created(event: object) -> None:
            dispatched.append(event)

        bus.register(TaskCreated, on_created)

        event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="fleur",
        )
        task = Task(
            task_id=TaskId(1),
            label="t",
            engine="fleur",
            state=Todo(),
            webhook_url=None,
            webhook_custom_params={},
            extra={},
            created_at=datetime(2025, 1, 1),
            updated_at=datetime(2025, 1, 1),
        )
        task = replace(task, events=(event,))

        bus_dispatch = bus.dispatch
        collected_events: list[object] = []

        class FakeUow:
            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *args: object) -> bool:
                return False

            async def publish_events(self) -> None:
                events = [event]
                collected_events.extend(events)
                await bus_dispatch(events)

            async def commit(self) -> None:
                await self.publish_events()

        async with FakeUow() as uow:
            await uow.commit()

        assert len(collected_events) == 1
        assert dispatched == [event]

    async def test_rollback_clears_without_dispatch(self) -> None:
        """Rollback clears saved tasks without dispatching events."""
        bus = MessageBus()
        dispatched: list[object] = []

        async def on_created(event: object) -> None:
            dispatched.append(event)

        bus.register(TaskCreated, on_created)

        class FakeUow:
            def __init__(self) -> None:
                self._saved_tasks: list[object] = ["placeholder"]

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *args: object) -> bool:
                return False

            async def rollback(self) -> None:
                self._saved_tasks.clear()

        uow = FakeUow()
        assert uow._saved_tasks == ["placeholder"]
        async with uow:
            await uow.rollback()
        assert uow._saved_tasks == []
        assert dispatched == []

    async def test_events_collected_from_multiple_aggregates(self) -> None:
        """Events from multiple saved aggregates are all dispatched."""
        bus = MessageBus()
        dispatched: list[object] = []

        async def on_created(event: object) -> None:
            dispatched.append(event)

        bus.register(TaskCreated, on_created)

        e1 = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="fleur",
        )
        e2 = TaskCreated(
            task_id=TaskId(2),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="vasp",
        )

        t1 = Task(
            task_id=TaskId(1),
            label="t1",
            engine="fleur",
            state=Todo(),
            webhook_url=None,
            webhook_custom_params={},
            extra={},
            created_at=datetime(2025, 1, 1),
            updated_at=datetime(2025, 1, 1),
        )
        t1 = replace(t1, events=(e1,))
        t2 = Task(
            task_id=TaskId(2),
            label="t2",
            engine="vasp",
            state=Todo(),
            webhook_url=None,
            webhook_custom_params={},
            extra={},
            created_at=datetime(2025, 1, 1),
            updated_at=datetime(2025, 1, 1),
        )
        t2 = replace(t2, events=(e2,))

        bus_dispatch = bus.dispatch

        class FakeUow:
            def __init__(self) -> None:
                self._saved: list[Task] = [t1, t2]

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *args: object) -> bool:
                return False

            async def collect_events(self) -> list[DomainEvent]:
                events: list[DomainEvent] = []
                for t in self._saved:
                    events.extend(t.events)
                self._saved.clear()
                return events

            async def publish_events(self) -> None:
                events = await self.collect_events()
                await bus_dispatch(events)
                self._saved.clear()

            async def commit(self) -> None:
                await self.publish_events()

        async with FakeUow() as uow:
            await uow.commit()

        assert len(dispatched) == 2
        assert dispatched[0] is e1
        assert dispatched[1] is e2
