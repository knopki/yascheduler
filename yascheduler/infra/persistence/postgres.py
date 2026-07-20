"""PostgreSQL repository implementations for tasks and nodes."""
# region MODULE_CONTRACT
# PURPOSE: Bridge domain repository ports to PostgreSQL so the orchestrator persists and loads tasks and nodes transactionally without coupling domain logic to pg8000 or SQL details.
# SCOPE: Async task and node CRUD over pg8000 via ThreadPoolExecutor.
# INVARIANTS: Every repository method is async and routes synchronous pg8000 calls through asyncio.get_running_loop().run_in_executor(self._executor, _fn).
# DEPENDENCIES: USES API: pg8000.Connection, READS: SQL files from disk via sql_loader
# KEYWORDS: postgres, repository, task, node, crud
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from yascheduler.domain import (
    NewNode,
    NewTask,
    Node,
    NodeId,
    NodeStatus,
    Task,
    TaskId,
    TaskStatus,
    materialize_task,
)

from .exceptions import TaskRowNotFoundError
from .sql_loader import load_query

if TYPE_CHECKING:
    from collections.abc import Mapping
    from concurrent.futures import ThreadPoolExecutor

    from pg8000.native import Connection

__all__ = ["PostgresNodeRepository", "PostgresTaskRepository"]


# region CLASS__PgRepository
# PURPOSE: Hold the shared pg8000.Connection and ThreadPoolExecutor so the two public repositories derive a single _run(sql, **params) helper without re-declaring the connection / executor wiring.
class _PgRepository:
    """Base for pg8000-backed repositories — holds connection, executor."""

    def __init__(self, conn: Connection, executor: ThreadPoolExecutor) -> None:
        self._conn = conn
        self._executor = executor

    # region METHOD__run
    # PURPOSE: Offload synchronous pg8000 calls to a thread-pool so async callers never block the event loop during SQL execution.
    async def _run(self, sql: str, **params: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        """Execute SQL via the thread pool and return rows as dicts keyed by column name."""

        def _fn() -> list[dict[str, Any]]:
            rows: list[tuple[Any, ...]] = self._conn.run(sql, **params) or []
            cols = [c["name"] for c in (self._conn.columns or [])]
            return [dict(zip(cols, row)) for row in rows]

        return await asyncio.get_running_loop().run_in_executor(self._executor, _fn)

    # endregion METHOD__run


# endregion CLASS__PgRepository


# region CLASS_PostgresTaskRepository
# PURPOSE: Persist and load tasks via PostgreSQL so the orchestrator's task lifecycle (submit, allocate, run, complete) survives restarts without coupling to pg8000.
class PostgresTaskRepository(_PgRepository):
    """PostgreSQL implementation of TaskRepository port."""

    def __init__(
        self,
        conn: Connection,
        executor: ThreadPoolExecutor,
        saved_tasks: list[Task] | None = None,
    ) -> None:
        """Initialise the repository with a DB connection."""
        super().__init__(conn, executor)
        self._saved_tasks = saved_tasks

    # region METHOD_get
    # PURPOSE: Retrieve a persisted task so the orchestrator can inspect its state before deciding the next lifecycle step (allocate, retry, complete).
    async def get(self, task_id: TaskId) -> Task | None:
        """Retrieve a task by ID, or None if not found.

        Passes ``task_id.value`` (the bare int) as the SQL param — pg8000 cannot
        adapt a ``TaskId`` dataclass.
        """
        rows = await self._run(load_query("task/get_by_id"), task_id=task_id.value)
        if not rows:
            return None
        return self._row_to_task(rows[0])

    # endregion METHOD_get

    # region METHOD_save
    # PURPOSE: Persist task mutations (status, allocation, error) so the latest state is durable — raises TaskRowNotFoundError to prevent silent data loss when the expected row is missing.
    # ENSURES: Raises TaskRowNotFoundError BEFORE appending to _saved_tasks when the targeted task_id does not exist.
    async def save(self, task: Task) -> None:
        """Persist task state to the database (update by task_id; raises on missing row)."""
        # region BLOCK_detect_zero_rows
        rows = await self._run(
            load_query("task/update_by_id"),
            task_id=task.task_id.value,
            title=task.label,
            engine=task.engine,
            remote_folder=task.remote_folder,
            local_folder=task.local_folder,
            webhook_url=task.webhook_url,
            error=task.error,
            webhook_custom_params=task.webhook_custom_params,
            extra=task.extra,
            status=task.status.name,
            node_id=task.allocated_node_id.value if task.allocated_node_id else None,
        )
        if not rows:
            raise TaskRowNotFoundError(task.task_id)
        # endregion BLOCK_detect_zero_rows
        if self._saved_tasks is not None:
            self._saved_tasks.append(task)

    # endregion METHOD_save

    # region METHOD_update_status
    # PURPOSE: Advance a task's lifecycle status atomically so concurrent observers see a consistent state and missing rows are detected via TaskRowNotFoundError.
    async def update_status(self, task_id: TaskId, status: TaskStatus) -> None:
        """Atomically update only the status field; raises on missing row."""
        # region BLOCK_detect_zero_rows
        rows = await self._run(
            load_query("task/update_status"),
            task_id=task_id.value,
            status=status.name,
        )
        if not rows:
            raise TaskRowNotFoundError(task_id)
        # endregion BLOCK_detect_zero_rows

    # endregion METHOD_update_status

    # region METHOD_list_ids_by_node_id_and_status
    # PURPOSE: Find tasks on a specific node in a given state so the orchestrator can decide whether to drain, decommission, or re-provision that node.
    async def list_ids_by_node_id_and_status(
        self,
        node_id: NodeId,
        status: TaskStatus,
    ) -> list[TaskId]:
        """Return task IDs allocated to the given node and matching the status."""
        rows = await self._run(
            load_query("task/get_ids_by_node_id_and_status"),
            node_id=node_id.value,
            status=status.name,
        )
        return [TaskId(int(row["task_id"])) for row in rows]

    # endregion METHOD_list_ids_by_node_id_and_status

    # region METHOD_insert
    # PURPOSE: Accept a new task submission so the orchestrator tracks it through its lifecycle — the returned Task carries a TaskCreated event for cross-layer notification.
    async def insert(self, new_task: NewTask) -> Task:
        """Insert a NewTask, return the persisted Task with TaskCreated in events."""
        rows = await self._run(
            load_query("task/insert"),
            title=new_task.label,
            engine=new_task.engine,
            remote_folder=None,
            local_folder=new_task.local_folder,
            webhook_url=new_task.webhook_url,
            webhook_custom_params=new_task.webhook_custom_params,
            extra=new_task.extra,
        )
        return materialize_task(self._row_to_task(rows[0]))

    # endregion METHOD_insert

    # region METHOD_list_by_status
    # PURPOSE: Poll for tasks matching a given state set so the orchestrator's main loop picks up the next batch of work to process.
    async def list_by_status(
        self,
        statuses: set[TaskStatus],
        limit: int | None = None,
    ) -> list[Task]:
        """Return tasks matching any of the given statuses."""
        rows = await self._run(
            load_query("task/list_by_status"),
            statuses=[s.name for s in statuses],
            lim=limit,
        )
        return [self._row_to_task(r) for r in rows]

    # endregion METHOD_list_by_status

    # region METHOD_list_by_jobs
    # PURPOSE: Batch-load tasks by explicit IDs so the client facade returns task details without issuing N+1 queries.
    async def list_by_jobs(self, job_ids: list[TaskId]) -> list[Task]:
        """Return tasks whose IDs are in the given list."""
        rows = await self._run(
            load_query("task/list_by_jobs"),
            task_ids=[tid.value for tid in job_ids],
        )
        return [self._row_to_task(r) for r in rows]

    # endregion METHOD_list_by_jobs

    # region METHOD_count_by_status
    # PURPOSE: Report per-status task tallies so dashboards, health checks, and CLI commands reflect the scheduler's workload without scanning all rows.
    async def count_by_status(self) -> Mapping[TaskStatus, int]:
        """Return a mapping of TaskStatus to task count."""
        rows = await self._run(load_query("task/count_by_status"))
        return {TaskStatus[row["status"]]: row["count"] for row in rows}

    # endregion METHOD_count_by_status

    # region METHOD__row_to_task
    # PURPOSE: Deserialize raw DB rows into domain Task entities so the application layer works with typed model objects, not raw dicts or manual JSON parsing.
    @staticmethod
    def _row_to_task(row: dict[str, Any]) -> Task:
        """Convert a DB row dict to a domain Task."""
        webhook_custom_params = row["webhook_custom_params"]
        if isinstance(webhook_custom_params, str):
            webhook_custom_params = json.loads(webhook_custom_params)
        extra = row["extra"]
        if isinstance(extra, str):
            extra = json.loads(extra)
        # Events are transient — always empty when loaded from DB.
        allocated_node_id_raw = row.get("allocated_node_id")
        return Task(
            task_id=TaskId(int(row["task_id"])),
            label=row.get("title", ""),
            engine=row["engine"],
            remote_folder=row.get("remote_folder"),
            local_folder=row.get("local_folder"),
            webhook_url=row.get("webhook_url"),
            error=row.get("error"),
            webhook_custom_params=webhook_custom_params,
            extra=extra,
            status=TaskStatus[row["status"]],
            allocated_node_id=(
                NodeId(int(allocated_node_id_raw))
                if allocated_node_id_raw is not None
                else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # endregion METHOD__row_to_task


# endregion CLASS_PostgresTaskRepository


# region CLASS_PostgresNodeRepository
# PURPOSE: Persist and load compute nodes via PostgreSQL so the orchestrator's node pool (enabled, disabled, cloud-provisioned) survives restarts without coupling to pg8000.
class PostgresNodeRepository(_PgRepository):
    """PostgreSQL implementation of NodeRepository port.

    ``insert(new_node: NewNode) -> Node`` is the sole node-insertion path
    (``add_tmp`` is removed); the tmp-reservation flow calls
    ``insert(NewNode(cloud=..., enabled=False))``. ``list_enabled`` and
    ``list_disabled`` have no python post-filter — by the invariant
    (``hostname == ''`` IFF ``enabled = FALSE`` AND the node is tmp/pending), no
    enabled row has ``hostname == ""`` (so the prior ``"." in r["hostname"]`` filter was
    dead in ``list_enabled``); ``list_disabled`` filters ``hostname <> ''`` in SQL
    (``node/list_disabled.sql``) so tmp rows are excluded at the DB layer.
    """

    # region METHOD_list_all
    # PURPOSE: Return the entire node inventory so management commands and CLI can enumerate, audit, or export all known nodes.
    async def list_all(self) -> list[Node]:
        """Return all nodes."""
        rows = await self._run(load_query("node/list_all"))
        return [self._row_to_node(r) for r in rows]

    # endregion METHOD_list_all

    # region METHOD_list_enabled
    # PURPOSE: List nodes available for scheduling so the allocator picks from active candidates without scanning disabled nodes.
    async def list_enabled(self) -> list[Node]:
        """Return enabled nodes (SQL WHERE enabled = TRUE is the only filter)."""
        rows = await self._run(load_query("node/list_enabled"))
        return [self._row_to_node(r) for r in rows]

    # endregion METHOD_list_enabled

    # region METHOD_list_disabled
    # PURPOSE: List nodes that are disabled but have a known hostname so operators can review or re-enable previously active nodes without seeing transient tmp rows.
    async def list_disabled(self) -> list[Node]:
        """Return disabled nodes with a real hostname (filter is in SQL, not python)."""
        rows = await self._run(load_query("node/list_disabled"))
        return [self._row_to_node(r) for r in rows]

    # endregion METHOD_list_disabled

    # region METHOD_insert
    # PURPOSE: Register a new compute node (SSH machine or cloud instance) so the orchestrator can track and allocate it via its assigned NodeId.
    async def insert(self, new_node: NewNode) -> Node:
        """Insert a NewNode, return the persisted Node with the generated NodeId."""
        rows = await self._run(
            load_query("node/insert"),
            hostname=new_node.hostname,
            ncpus=new_node.ncpus,
            enabled=new_node.enabled,
            cloud=new_node.cloud,
            username=new_node.username,
            port=new_node.port,
            jump_host=new_node.jump_host,
            jump_port=new_node.jump_port,
            jump_username=new_node.jump_username,
            external_id=new_node.external_id,
            status=new_node.status.value,
        )
        # RETURNING yields node_id, created_at, updated_at; merge with input
        # values so _row_to_node has the full row.
        row = {
            **rows[0],
            "hostname": new_node.hostname,
            "ncpus": new_node.ncpus,
            "enabled": new_node.enabled,
            "cloud": new_node.cloud,
            "username": new_node.username,
            "port": new_node.port,
            "jump_host": new_node.jump_host,
            "jump_port": new_node.jump_port,
            "jump_username": new_node.jump_username,
            "external_id": new_node.external_id,
            "status": new_node.status.value,
        }
        return self._row_to_node(row)

    # endregion METHOD_insert

    # region METHOD_get_by_id
    # PURPOSE: Retrieve a specific node by ID so the orchestrator can inspect its state before scheduling or decommissioning it.
    async def get_by_id(self, node_id: NodeId) -> Node | None:
        """Retrieve a node by primary key, or None if not found.

        Passes ``node_id.value`` (the bare int) as the SQL param — pg8000 cannot
        adapt a ``NodeId`` dataclass.
        """
        rows = await self._run(load_query("node/get_by_id"), node_id=node_id.value)
        if not rows:
            return None
        return self._row_to_node(rows[0])

    # endregion METHOD_get_by_id

    # region METHOD_get_by_ids
    # PURPOSE: Batch-load nodes by ID list so the orchestrator resolves many node references in one query instead of N round-trips.
    async def get_by_ids(self, node_ids: list[NodeId]) -> dict[NodeId, Node]:
        """Return nodes keyed by NodeId for the given primary-key list.

        Passes ``[n.value for n in node_ids]`` (the bare ints) as the SQL
        param — pg8000 adapts a Python list to a PostgreSQL array for
        ``= ANY(:node_ids)``. An empty list runs the SQL with an empty array
        and returns an empty dict.
        """
        rows = await self._run(
            load_query("node/get_by_ids"),
            node_ids=[n.value for n in node_ids],
        )
        return {NodeId(int(row["node_id"])): self._row_to_node(row) for row in rows}

    # endregion METHOD_get_by_ids

    # region METHOD_update
    # PURPOSE: Persist node mutations (hostname, status, cloud properties) so the orchestrator's view of each node remains current across restarts.
    async def update(self, node: Node) -> None:
        """Persist all mutable node fields by node_id."""
        await self._run(
            load_query("node/update"),
            node_id=node.node_id.value,
            hostname=node.hostname,
            ncpus=node.ncpus,
            enabled=node.enabled,
            cloud=node.cloud,
            username=node.username,
            port=node.port,
            jump_host=node.jump_host,
            jump_port=node.jump_port,
            jump_username=node.jump_username,
            external_id=node.external_id,
            status=node.status.value,
        )

    # endregion METHOD_update

    # region METHOD_enable
    # PURPOSE: Mark a node as available for scheduling so the allocator considers it in future allocation rounds.
    async def enable(self, node_id: NodeId) -> None:
        """Enable a node by node_id (passes node_id.value — pg8000 cannot adapt a NodeId)."""
        await self._run(load_query("node/enable"), node_id=node_id.value)

    # endregion METHOD_enable

    # region METHOD_disable
    # PURPOSE: Mark a node as unavailable (drain or decommission) so the allocator avoids scheduling new tasks on it.
    async def disable(self, node_id: NodeId) -> None:
        """Disable a node by node_id (passes node_id.value — pg8000 cannot adapt a NodeId)."""
        await self._run(load_query("node/disable"), node_id=node_id.value)

    # endregion METHOD_disable

    # region METHOD_remove
    # PURPOSE: Remove a decommissioned or failed node from inventory so it no longer appears in listing or allocation queries.
    async def remove(self, node_id: NodeId) -> None:
        """Delete a node by node_id (passes node_id.value — pg8000 cannot adapt a NodeId)."""
        await self._run(load_query("node/remove"), node_id=node_id.value)

    # endregion METHOD_remove

    # region METHOD_count_by_cloud
    # PURPOSE: Report per-provider node tallies so cost dashboards and capacity planning see distribution across cloud backends.
    async def count_by_cloud(self) -> Mapping[str, int]:
        """Return a mapping of cloud provider to node count."""
        rows = await self._run(load_query("node/count_by_cloud"))
        return {row["cloud"]: row["count"] for row in rows}

    # endregion METHOD_count_by_cloud

    # region METHOD_count_by_status
    # PURPOSE: Report enabled/disabled node counts so operators gauge cluster capacity at a glance.
    async def count_by_status(self) -> Mapping[bool, int]:
        """Return a mapping of enabled (bool) to node count."""
        rows = await self._run(load_query("node/count_by_status"))
        return {bool(row["enabled"]): row["count"] for row in rows}

    # endregion METHOD_count_by_status

    # region METHOD__row_to_node
    # PURPOSE: Deserialize raw DB rows into domain Node entities so the application layer works with typed model objects, not raw dicts.
    @staticmethod
    def _row_to_node(row: dict[str, Any]) -> Node:
        """Convert a DB row dict to a domain Node."""
        return Node(
            node_id=NodeId(int(row["node_id"])),
            hostname=row.get("hostname", ""),
            ncpus=row.get("ncpus"),
            enabled=bool(row.get("enabled", False)),
            cloud=row.get("cloud"),
            username=row.get("username", "root"),
            port=row.get("port", 22),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            jump_host=row.get("jump_host"),
            jump_port=row.get("jump_port", 22),
            jump_username=row.get("jump_username", "root"),
            external_id=row.get("external_id"),
            status=NodeStatus[row["status"]],
        )

    # endregion METHOD__row_to_node


# endregion CLASS_PostgresNodeRepository
