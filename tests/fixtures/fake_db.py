# FILE: tests/fixtures/fake_db.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: In-memory FakeDB implementing the DB public interface for reuse in scheduler/orchestration tests.
#   SCOPE: Node/task CRUD in memory with real TaskModel/NodeModel returns, auto-incrementing task_id.
#   DEPENDS: M-DB
#   LINKS: M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   FakeDB - In-memory DB replacement for tests
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial FakeDB implementation
# END_CHANGE_SUMMARY

from collections.abc import Mapping, Sequence
from typing import Any, Optional

from yascheduler.db import NodeModel, TaskModel, TaskStatus


# START_CONTRACT: FakeDB
#   PURPOSE: In-memory dict-backed implementation of the DB public interface, returning real TaskModel/NodeModel objects with auto-incrementing task_id
#   INPUTS: { None - no constructor args required }
#   OUTPUTS: { FakeDB - initialized instance with empty nodes and tasks dicts }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: FakeDB
class FakeDB:
    """In-memory database double for tests"""

    # START_CONTRACT: __init__
    #   PURPOSE: Initialize empty in-memory storage for nodes and tasks with auto-increment counter at 1
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Initializes _nodes dict, _tasks dict, _next_task_id counter
    #   LINKS: [M-DB]
    # END_CONTRACT: __init__
    def __init__(self) -> None:
        self._nodes: dict[str, NodeModel] = {}
        self._tasks: dict[int, TaskModel] = {}
        self._next_task_id = 1

    # START_CONTRACT: add_node
    #   PURPOSE: Insert a new compute node record in-memory
    #   INPUTS: { ip_addr: str - node IP, username: str - SSH username }
    #            { port: Optional[int] - SSH port (default 22) }
    #            { ncpus: Optional[int] - CPU count }
    #            { cloud: Optional[str] - cloud provider name }
    #            { enabled: bool - whether node is enabled (default False) }
    #   OUTPUTS: { NodeModel - newly created node data }
    #   SIDE_EFFECTS: Stores node in internal dict
    #   LINKS: [M-DB]
    # END_CONTRACT: add_node
    async def add_node(
        self,
        ip_addr: str,
        username: str,
        port: Optional[int] = 22,
        ncpus: Optional[int] = None,
        cloud: Optional[str] = None,
        enabled: bool = False,
    ) -> NodeModel:
        port = port or 22
        node = NodeModel(
            ip=ip_addr,
            ncpus=ncpus,
            enabled=enabled,
            cloud=cloud,
            username=username,
            port=port,
        )
        self._nodes[ip_addr] = node
        return node

    # START_CONTRACT: get_node
    #   PURPOSE: Retrieve a node by its IP address
    #   INPUTS: { ip_addr: str - node IP }
    #   OUTPUTS: { Optional[NodeModel] - node if found, None otherwise }
    #   SIDE_EFFECTS: None
    #   LINKS: [M-DB]
    # END_CONTRACT: get_node
    async def get_node(self, ip_addr: str) -> Optional[NodeModel]:
        return self._nodes.get(ip_addr)

    # START_CONTRACT: get_all_nodes
    #   PURPOSE: Return all known nodes
    #   INPUTS: { None }
    #   OUTPUTS: { Sequence[NodeModel] - all stored nodes }
    #   SIDE_EFFECTS: None
    #   LINKS: [M-DB]
    # END_CONTRACT: get_all_nodes
    async def get_all_nodes(self) -> Sequence[NodeModel]:
        return list(self._nodes.values())

    # START_CONTRACT: enable_node
    #   PURPOSE: Enable a node for task scheduling
    #   INPUTS: { ip_addr: str - node IP to enable }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Updates node's enabled flag to True
    #   LINKS: [M-DB]
    # END_CONTRACT: enable_node
    async def enable_node(self, ip_addr: str) -> None:
        node = self._nodes.get(ip_addr)
        if node:
            self._nodes[ip_addr] = NodeModel(
                ip=node.ip,
                ncpus=node.ncpus,
                enabled=True,
                cloud=node.cloud,
                username=node.username,
                port=node.port,
            )

    # START_CONTRACT: disable_node
    #   PURPOSE: Disable a node from task scheduling
    #   INPUTS: { ip_addr: str - node IP to disable }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Updates node's enabled flag to False
    #   LINKS: [M-DB]
    # END_CONTRACT: disable_node
    async def disable_node(self, ip_addr: str) -> None:
        node = self._nodes.get(ip_addr)
        if node:
            self._nodes[ip_addr] = NodeModel(
                ip=node.ip,
                ncpus=node.ncpus,
                enabled=False,
                cloud=node.cloud,
                username=node.username,
                port=node.port,
            )

    # START_CONTRACT: remove_node
    #   PURPOSE: Delete a node by its IP address
    #   INPUTS: { ip_addr: str - node IP to remove }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Removes node from internal storage if present
    #   LINKS: [M-DB]
    # END_CONTRACT: remove_node
    async def remove_node(self, ip_addr: str) -> None:
        self._nodes.pop(ip_addr, None)

    # START_CONTRACT: add_task
    #   PURPOSE: Insert a new task in-memory with auto-incremented ID
    #   INPUTS: { label: Optional[str] - task label }
    #            { ip_addr: Optional[str] - node IP }
    #            { status: TaskStatus - initial status (default TO_DO) }
    #            { metadata: Optional[Mapping[str, Any]] - task metadata }
    #   OUTPUTS: { TaskModel - newly created task with generated ID }
    #   SIDE_EFFECTS: Stores task in internal dict; increments task ID counter
    #   LINKS: [M-DB]
    # END_CONTRACT: add_task
    async def add_task(
        self,
        label: Optional[str] = None,
        ip_addr: Optional[str] = None,
        status: TaskStatus = TaskStatus.TO_DO,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> TaskModel:
        tid = self._next_task_id
        self._next_task_id += 1
        task = TaskModel(
            task_id=tid,
            label=label or "",
            ip=ip_addr or "",
            status=status,
            metadata=metadata or {},
        )
        self._tasks[tid] = task
        return task

    # START_CONTRACT: get_task
    #   PURPOSE: Retrieve a single task by its ID
    #   INPUTS: { task_id: int - unique task identifier }
    #   OUTPUTS: { Optional[TaskModel] - task if found, None otherwise }
    #   SIDE_EFFECTS: None
    #   LINKS: [M-DB]
    # END_CONTRACT: get_task
    async def get_task(self, task_id: int) -> Optional[TaskModel]:
        return self._tasks.get(task_id)

    # START_CONTRACT: update_task_status
    #   PURPOSE: Update the status of an existing task
    #   INPUTS: { task_id: int - task to update }
    #            { status: TaskStatus - new status value }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Creates new TaskModel with updated status; no-op if task not found
    #   LINKS: [M-DB]
    # END_CONTRACT: update_task_status
    async def update_task_status(self, task_id: int, status: TaskStatus) -> None:
        task = self._tasks.get(task_id)
        if task:
            self._tasks[task_id] = TaskModel(
                task_id=task.task_id,
                label=task.label,
                ip=task.ip,
                status=status,
                metadata=task.metadata,
                cloud=task.cloud,
            )

    # START_CONTRACT: set_task_running
    #   PURPOSE: Mark task as RUNNING and bind it to a node IP
    #   INPUTS: { task_id: int - task to update }
    #            { ip_addr: str - node IP the task runs on }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Creates new TaskModel with RUNNING status and IP; no-op if task not found
    #   LINKS: [M-DB]
    # END_CONTRACT: set_task_running
    async def set_task_running(self, task_id: int, ip_addr: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            self._tasks[task_id] = TaskModel(
                task_id=task.task_id,
                label=task.label,
                ip=ip_addr,
                status=TaskStatus.RUNNING,
                metadata=task.metadata,
                cloud=task.cloud,
            )

    # START_CONTRACT: set_task_done
    #   PURPOSE: Set task status to DONE and update its metadata
    #   INPUTS: { task_id: int - task to mark done }
    #            { metadata: Mapping[str, Any] - final metadata snapshot }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Creates new TaskModel with DONE status and provided metadata;
    #                 no-op if task not found
    #   LINKS: [M-DB]
    # END_CONTRACT: set_task_done
    async def set_task_done(self, task_id: int, metadata: Mapping[str, Any]) -> None:
        task = self._tasks.get(task_id)
        if task:
            self._tasks[task_id] = TaskModel(
                task_id=task.task_id,
                label=task.label,
                ip=task.ip,
                status=TaskStatus.DONE,
                metadata=metadata,
                cloud=task.cloud,
            )

    # START_CONTRACT: set_task_error
    #   PURPOSE: Mark task as DONE with error metadata (embeds error in metadata if provided)
    #   INPUTS: { task_id: int - task to mark }
    #            { metadata: Mapping[str, Any] - existing metadata }
    #            { error: Optional[str] - error message to embed in metadata }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Creates new TaskModel with DONE status;
    #                 appends error key to metadata when error is provided;
    #                 no-op if task not found
    #   LINKS: [M-DB]
    # END_CONTRACT: set_task_error
    async def set_task_error(
        self,
        task_id: int,
        metadata: Mapping[str, Any],
        error: Optional[str] = None,
    ) -> None:
        new_meta = (
            dict(list(metadata.items()) + [("error", error)]) if error else metadata
        )
        task = self._tasks.get(task_id)
        if task:
            self._tasks[task_id] = TaskModel(
                task_id=task.task_id,
                label=task.label,
                ip=task.ip,
                status=TaskStatus.DONE,
                metadata=new_meta,
                cloud=task.cloud,
            )
