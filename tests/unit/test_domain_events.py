# FILE: tests/unit/test_domain_events.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain events and Task aggregate event support.
#   SCOPE: Event construction, immutability, Event union type, Task.record_event, Task.pull_events.
#   DEPENDS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestDomainEvents - Construction, immutability, union type for all event types
#   TestTaskEvents - record_event, pull_events, integration
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Domain event and Task aggregate event tests.
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
from yascheduler.domain.model import Task, TaskContext, TaskStatus


class TestDomainEvents:
    def test_task_created_all_fields(self) -> None:
        evt = TaskCreated(
            task_id=1,
            webhook_url="https://example.com/hook",
            webhook_custom_params={"key": "val"},
            engine_name="fleur",
        )
        assert evt.task_id == 1
        assert evt.webhook_url == "https://example.com/hook"
        assert evt.webhook_custom_params == {"key": "val"}
        assert evt.engine_name == "fleur"

    def test_task_created_defaults(self) -> None:
        evt = TaskCreated(task_id=2, webhook_url=None, engine_name="cp2k")
        assert evt.webhook_url is None
        assert evt.webhook_custom_params == {}

    def test_task_allocated_all_fields(self) -> None:
        evt = TaskAllocated(
            task_id=3,
            webhook_url=None,
            engine_name="fleur",
            node_ip="10.0.0.1",
        )
        assert evt.task_id == 3
        assert evt.node_ip == "10.0.0.1"
        assert evt.engine_name == "fleur"

    def test_task_completed_all_fields(self) -> None:
        evt = TaskCompleted(
            task_id=4,
            webhook_url=None,
            local_folder="/results/4",
            has_errors=True,
        )
        assert evt.local_folder == "/results/4"
        assert evt.has_errors is True

    def test_task_failed_all_fields(self) -> None:
        evt = TaskFailed(task_id=5, webhook_url=None, reason="OOM")
        assert evt.reason == "OOM"

    def test_task_abandoned_all_fields(self) -> None:
        evt = TaskAbandoned(task_id=6, webhook_url=None, node_ip="10.0.0.5")
        assert evt.node_ip == "10.0.0.5"

    def test_frozen_enforcement(self) -> None:
        evt = TaskCreated(task_id=1, webhook_url=None, engine_name="cp2k")
        with pytest.raises(FrozenInstanceError):
            evt.task_id = 99  # type: ignore[misc]

    def test_event_union_isinstance(self) -> None:
        created: Event = TaskCreated(task_id=1, webhook_url=None, engine_name="cp2k")
        allocated: Event = TaskAllocated(
            task_id=1, webhook_url=None, engine_name="cp2k", node_ip="10.0.0.1"
        )
        completed: Event = TaskCompleted(
            task_id=1, webhook_url=None, local_folder="/r", has_errors=False
        )
        failed: Event = TaskFailed(task_id=1, webhook_url=None, reason="err")
        abandoned: Event = TaskAbandoned(
            task_id=1, webhook_url=None, node_ip="10.0.0.1"
        )

        assert isinstance(created, TaskCreated)
        assert isinstance(allocated, TaskAllocated)
        assert isinstance(completed, TaskCompleted)
        assert isinstance(failed, TaskFailed)
        assert isinstance(abandoned, TaskAbandoned)
        assert not isinstance(created, TaskFailed)

    def test_all_events_are_domain_event(self) -> None:
        for evt in (
            TaskCreated(task_id=1, webhook_url=None, engine_name="cp2k"),
            TaskAllocated(
                task_id=1, webhook_url=None, engine_name="cp2k", node_ip="10.0.0.1"
            ),
            TaskCompleted(
                task_id=1, webhook_url=None, local_folder="/r", has_errors=False
            ),
            TaskFailed(task_id=1, webhook_url=None, reason="err"),
            TaskAbandoned(task_id=1, webhook_url=None, node_ip="10.0.0.1"),
        ):
            assert isinstance(evt, DomainEvent)


def _make_task(**overrides: object) -> Task:
    ctx = TaskContext(engine="fleur")
    base: dict[str, object] = dict(task_id=1, label="test", context=ctx)
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


class TestTaskEvents:
    def test_record_event_returns_new_task(self) -> None:
        task = _make_task()
        event = TaskCreated(task_id=1, webhook_url=None, engine_name="fleur")
        updated = task.record_event(event)
        assert updated._events == (event,)
        assert task._events == ()

    def test_pull_events_returns_clean_task_and_events(self) -> None:
        event = TaskCreated(task_id=1, webhook_url=None, engine_name="fleur")
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
        e1 = TaskCreated(task_id=1, webhook_url=None, engine_name="fleur")
        e2 = TaskAllocated(
            task_id=1, webhook_url=None, engine_name="fleur", node_ip="10.0.0.1"
        )
        e3 = TaskCompleted(
            task_id=1, webhook_url=None, local_folder="/r", has_errors=False
        )

        task = task.record_event(e1)
        task = task.record_event(e2)
        task = task.record_event(e3)

        clean, events = task.pull_events()
        assert events == (e1, e2, e3)
        assert clean._events == ()
        assert clean.task_id == 1
        assert clean.status == TaskStatus.TO_DO
