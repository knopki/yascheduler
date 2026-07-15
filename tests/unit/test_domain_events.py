# FILE: tests/unit/test_domain_events.py
# VERSION: 1.4.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain events and Task aggregate event support.
#   SCOPE: Event construction, immutability, Event union type, TaskCompleted has_errors removed, materialize_task attaches TaskCreated.
#   DEPENDS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestDomainEvents - Construction, immutability, union type for all event types
#   TestTaskCompletedNoHasErrors - TaskCompleted has no has_errors field
#   TestMaterializeTask - materialize_task attaches TaskCreated event
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - drop-task-context-entity: update Task construction (flat fields, no TaskContext); remove TaskContext import.
#   PREVIOUS_CHANGE: v1.3.0 - task-schema-and-entity-cleanup: fixtures use allocated_node_id (was allocated_ip); orchestrator MACHINE_GONE log no longer includes ip.
#   PREVIOUS_CHANGE: v1.2.0 - Add TestTaskWithEvent suite for task.with_event factory (task-with-event).
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
from yascheduler.domain.model import NodeId, Task, TaskId, materialize_task


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
        )
        assert evt.local_folder == "/results/4"

    def test_task_failed_all_fields(self) -> None:
        evt = TaskFailed(
            task_id=TaskId(5),
            webhook_url=None,
            webhook_custom_params={},
            reason="OOM",
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
        )
        failed: Event = TaskFailed(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            reason="err",
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
    from datetime import datetime

    base: dict[str, object] = {
        "task_id": TaskId(1),
        "label": "test",
        "engine": "fleur",
        "remote_folder": None,
        "local_folder": None,
        "webhook_url": None,
        "webhook_custom_params": {},
        "error": None,
        "extra": {},
        "created_at": datetime(2025, 1, 1),
        "updated_at": datetime(2025, 1, 1),
    }
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


class TestTaskCompletedNoHasErrors:
    def test_task_completed_has_no_has_errors_field(self) -> None:
        event = TaskCompleted(
            task_id=TaskId(42),
            webhook_url=None,
            webhook_custom_params={},
            local_folder="/out",
        )
        assert not hasattr(event, "has_errors")


class TestMaterializeTask:
    def test_materialize_task_attaches_task_created(self) -> None:
        from datetime import datetime

        task = Task(
            task_id=TaskId(1),
            label="test",
            engine="fleur",
            remote_folder=None,
            local_folder=None,
            webhook_url="https://hook.example.com",
            webhook_custom_params={"k": "v"},
            error=None,
            extra={},
            created_at=datetime(2025, 1, 1),
            updated_at=datetime(2025, 1, 1),
            events=(),
        )
        result = materialize_task(task)
        assert len(result.events) == 1
        evt = result.events[0]
        assert isinstance(evt, TaskCreated)
        assert evt.task_id == TaskId(1)
        assert evt.webhook_url == "https://hook.example.com"
        assert evt.webhook_custom_params == {"k": "v"}
        assert evt.engine_name == "fleur"
