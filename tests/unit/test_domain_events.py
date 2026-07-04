# FILE: tests/unit/test_domain_events.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain events and Task aggregate event support.
#   SCOPE: Event construction, immutability, Event union type, Task.record_event, Task.pull_events, Task.with_event.
#   DEPENDS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestDomainEvents - Construction, immutability, union type for all event types
#   TestTaskEvents - record_event, pull_events, integration
#   TestTaskWithEvent - with_event factory: base-field substitution, keyword-only subclass fields, collision pop, fail preservation, record_event coexistence
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Add TestTaskWithEvent suite for task.with_event factory (task-with-event).
#   PREVIOUS_CHANGE: v1.1.0 - Pass webhook_custom_params explicitly (field is now required for Python 3.9 compat); replace test_task_created_defaults with test_webhook_custom_params_stored.
# END_CHANGE_SUMMARY

from dataclasses import FrozenInstanceError

import pytest

from yascheduler.domain.events import (
    DomainEvent,
    Event,
    TaskAbandoned,
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)
from yascheduler.domain.model import NodeId, Task, TaskContext, TaskId, TaskStatus


class TestDomainEvents:
    def test_task_created_all_fields(self) -> None:
        evt = TaskCreated(
            task_id=TaskId(1),
            webhook_url="https://example.com/hook",
            webhook_custom_params={"key": "val"},
            engine_name="fleur",
        )
        assert evt.task_id == TaskId(1)
        assert evt.webhook_url == "https://example.com/hook"
        assert evt.webhook_custom_params == {"key": "val"}
        assert evt.engine_name == "fleur"

    def test_webhook_custom_params_stored(self) -> None:
        evt = TaskCreated(
            task_id=TaskId(2),
            webhook_url=None,
            webhook_custom_params={"k": "v"},
            engine_name="cp2k",
        )
        assert evt.webhook_custom_params == {"k": "v"}

    def test_task_allocated_all_fields(self) -> None:
        evt = TaskAllocated(
            task_id=TaskId(3),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="fleur",
            node_id=NodeId(3),
        )
        assert evt.task_id == TaskId(3)
        assert evt.node_id == NodeId(3)
        assert evt.engine_name == "fleur"

    def test_task_completed_all_fields(self) -> None:
        evt = TaskCompleted(
            task_id=TaskId(4),
            webhook_url=None,
            webhook_custom_params={},
            local_folder="/results/4",
            has_errors=True,
        )
        assert evt.local_folder == "/results/4"
        assert evt.has_errors is True

    def test_task_failed_all_fields(self) -> None:
        evt = TaskFailed(
            task_id=TaskId(5), webhook_url=None, webhook_custom_params={}, reason="OOM"
        )
        assert evt.reason == "OOM"

    def test_task_abandoned_all_fields(self) -> None:
        evt = TaskAbandoned(
            task_id=TaskId(6),
            webhook_url=None,
            webhook_custom_params={},
            node_id=NodeId(6),
        )
        assert evt.node_id == NodeId(6)

    def test_frozen_enforcement(self) -> None:
        evt = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="cp2k",
        )
        with pytest.raises(FrozenInstanceError):
            evt.task_id = TaskId(99)  # type: ignore[misc]

    def test_event_union_isinstance(self) -> None:
        created: Event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="cp2k",
        )
        allocated: Event = TaskAllocated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="cp2k",
            node_id=NodeId(1),
        )
        completed: Event = TaskCompleted(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            local_folder="/r",
            has_errors=False,
        )
        failed: Event = TaskFailed(
            task_id=TaskId(1), webhook_url=None, webhook_custom_params={}, reason="err"
        )
        abandoned: Event = TaskAbandoned(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            node_id=NodeId(1),
        )

        assert isinstance(created, TaskCreated)
        assert isinstance(allocated, TaskAllocated)
        assert isinstance(completed, TaskCompleted)
        assert isinstance(failed, TaskFailed)
        assert isinstance(abandoned, TaskAbandoned)
        assert not isinstance(created, TaskFailed)

    def test_all_events_are_domain_event(self) -> None:
        for evt in (
            TaskCreated(
                task_id=TaskId(1),
                webhook_url=None,
                webhook_custom_params={},
                engine_name="cp2k",
            ),
            TaskAllocated(
                task_id=TaskId(1),
                webhook_url=None,
                webhook_custom_params={},
                engine_name="cp2k",
                node_id=NodeId(1),
            ),
            TaskCompleted(
                task_id=TaskId(1),
                webhook_url=None,
                webhook_custom_params={},
                local_folder="/r",
                has_errors=False,
            ),
            TaskFailed(
                task_id=TaskId(1),
                webhook_url=None,
                webhook_custom_params={},
                reason="err",
            ),
            TaskAbandoned(
                task_id=TaskId(1),
                webhook_url=None,
                webhook_custom_params={},
                node_id=NodeId(1),
            ),
        ):
            assert isinstance(evt, DomainEvent)


def _make_task(**overrides: object) -> Task:
    ctx = TaskContext(engine="fleur")
    base: dict[str, object] = dict(task_id=TaskId(1), label="test", context=ctx)
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


class TestTaskEvents:
    def test_record_event_returns_new_task(self) -> None:
        task = _make_task()
        event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="fleur",
        )
        updated = task.record_event(event)
        assert updated._events == (event,)
        assert task._events == ()

    def test_pull_events_returns_clean_task_and_events(self) -> None:
        event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="fleur",
        )
        task = _make_task(_events=(event,))
        clean, events = task.pull_events()
        assert clean._events == ()
        assert events == (event,)
        assert task._events == (event,)

    def test_pull_events_empty(self) -> None:
        task = _make_task()
        clean, events = task.pull_events()
        assert clean._events == ()
        assert events == ()
        assert clean.task_id == task.task_id

    def test_record_and_pull_integration(self) -> None:
        task = _make_task()
        e1 = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="fleur",
        )
        e2 = TaskAllocated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="fleur",
            node_id=NodeId(1),
        )
        e3 = TaskCompleted(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            local_folder="/r",
            has_errors=False,
        )

        task = task.record_event(e1)
        task = task.record_event(e2)
        task = task.record_event(e3)

        clean, events = task.pull_events()
        assert events == (e1, e2, e3)
        assert clean._events == ()
        assert clean.task_id == TaskId(1)
        assert clean.status == TaskStatus.TO_DO


def _make_task_with_webhook(**overrides: object) -> Task:
    ctx = TaskContext(
        engine="fleur",
        webhook_url="https://hook.example.com",
        webhook_custom_params={"k": "v"},
    )
    base: dict[str, object] = dict(task_id=TaskId(42), label="test", context=ctx)
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


class TestTaskWithEvent:
    def test_populates_base_fields_from_context(self) -> None:
        task = _make_task_with_webhook()
        updated = task.with_event(
            TaskAllocated, node_id=NodeId(42), engine_name="fleur"
        )
        assert len(updated._events) == 1
        evt = updated._events[0]
        assert isinstance(evt, TaskAllocated)
        assert evt.task_id == TaskId(42)
        assert evt.webhook_url == "https://hook.example.com"
        assert evt.webhook_custom_params == {"k": "v"}
        assert evt.node_id == NodeId(42)
        assert evt.engine_name == "fleur"

    def test_subclass_fields_are_keyword_only(self) -> None:
        task = _make_task_with_webhook()
        with pytest.raises(TypeError):
            task.with_event(TaskAllocated, "10.0.0.1", "fleur")  # type: ignore[call-overload]

    def test_silently_drops_base_field_collisions(self) -> None:
        task = _make_task_with_webhook()
        updated = task.with_event(
            TaskCreated,  # type: ignore[call-overload]
            engine_name="fleur",
            webhook_url="https://other.example.com",
        )
        evt = updated._events[0]
        assert isinstance(evt, TaskCreated)
        assert evt.webhook_url == "https://hook.example.com"
        assert evt.webhook_custom_params == {"k": "v"}

    def test_delegates_to_record_event_via_pull_events(self) -> None:
        task = _make_task_with_webhook()
        updated = task.with_event(TaskCompleted, local_folder="/out", has_errors=False)
        clean, events = updated.pull_events()
        assert clean._events == ()
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, TaskCompleted)
        assert evt.local_folder == "/out"
        assert evt.has_errors is False
        assert evt.task_id == TaskId(42)

    def test_with_event_after_fail_reads_preserved_webhook_fields(self) -> None:
        running = _make_task_with_webhook(
            status=TaskStatus.RUNNING, allocated_ip="10.0.0.9"
        )
        failed = running.fail("node is gone")
        updated = failed.with_event(TaskAbandoned, node_id=NodeId(42))
        evt = updated._events[0]
        assert isinstance(evt, TaskAbandoned)
        assert evt.node_id == NodeId(42)
        assert evt.webhook_url == "https://hook.example.com"
        assert evt.webhook_custom_params == {"k": "v"}

    def test_record_event_still_works_as_low_level_primitive(self) -> None:
        task = _make_task_with_webhook()
        event = TaskFailed(
            task_id=TaskId(42),
            webhook_url=None,
            webhook_custom_params={},
            reason="manual",
        )
        via_record = task.record_event(event)
        via_with = task.with_event(TaskFailed, reason="manual")
        rec_evt = via_record._events[0]
        with_evt = via_with._events[0]
        assert isinstance(rec_evt, TaskFailed)
        assert isinstance(with_evt, TaskFailed)
        assert rec_evt.reason == "manual"
        assert with_evt.reason == "manual"
