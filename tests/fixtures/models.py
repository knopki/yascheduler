# FILE: tests/fixtures/models.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Test data helpers for creating TaskModel and NodeModel instances with sensible defaults.
#   SCOPE: Factory functions for test data construction.
#   DEPENDS: M-DB
#   LINKS: M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   make_task - create TaskModel with defaults and keyword overrides
#   make_node - create NodeModel with defaults and keyword overrides
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial test data helpers
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import Any

from yascheduler.db import NodeModel, TaskModel, TaskStatus


# START_CONTRACT: make_task
#   PURPOSE: Create a TaskModel with sensible defaults and keyword overrides.
#   INPUTS: { overrides: Any - keyword overrides for task_id, label, ip, status, metadata, cloud }
#   OUTPUTS: { TaskModel - constructed task instance }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: make_task
def make_task(**overrides: Any) -> TaskModel:  # noqa: ANN401
    task_id: int = overrides.get("task_id", 1)
    label: str = overrides.get("label", "test-task")
    ip: str = overrides.get("ip", "127.0.0.1")
    status: TaskStatus = overrides.get("status", TaskStatus.TO_DO)
    return TaskModel(
        task_id=task_id,
        label=label,
        ip=ip,
        status=status,
        metadata=overrides.get("metadata", {}),
        cloud=overrides.get("cloud"),
    )


# START_CONTRACT: make_node
#   PURPOSE: Create a NodeModel with sensible defaults and keyword overrides.
#   INPUTS: { overrides: Any - keyword overrides for ip, ncpus, enabled, cloud, username, port }
#   OUTPUTS: { NodeModel - constructed node instance }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: make_node
def make_node(**overrides: Any) -> NodeModel:  # noqa: ANN401
    ip: str = overrides.get("ip", "192.168.1.1")
    ncpus: int | None = overrides.get("ncpus", 4)
    return NodeModel(
        ip=ip,
        ncpus=ncpus,
        enabled=overrides.get("enabled", True),
        cloud=overrides.get("cloud"),
        username=overrides.get("username", "root"),
        port=overrides.get("port", 22),
    )
