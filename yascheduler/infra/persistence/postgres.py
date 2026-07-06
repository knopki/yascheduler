# FILE: yascheduler/infra/persistence/postgres.py
# VERSION: 1.11.1
# START_MODULE_CONTRACT
#   PURPOSE: PostgreSQL repository implementations for tasks and nodes.
#   SCOPE: _PgRepository base, PostgresTaskRepository and PostgresNodeRepository wrappers around pg8000 Connection.
#   DEPENDS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-EXCEPTIONS, M-DOMAIN-MODEL, M-DOMAIN-PORTS
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-EXCEPTIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _PgRepository - base class for pg8000-backed repositories (conn, executor, _run)
#   PostgresTaskRepository - async task CRUD: get, save, update_status, insert (NewTask→Task), list_by_status, list_by_jobs, count_by_status; get/update_status/save/list_by_jobs take/return TaskId (.value passed as pg8000 param); list_ids_by_node_id_and_status returns list[TaskId]; _row_to_task wraps TaskId and NodeId, reads created_at/updated_at, reads status via TaskStatus[name] (name lookup, was int cast); save/insert bind allocated_node_id via :node_id param, write status via status.name (enum-label string); save/update_status raise TaskRowNotFoundError on 0-row UPDATE
#   PostgresNodeRepository - async node CRUD: get_by_id, get_by_ids (batch, WHERE node_id = ANY(:node_ids)), list_*, insert (NewNode→Node, sole insertion path — add_tmp removed), update (keys on node_id), enable/disable/remove (take NodeId, pass node_id.value), count_*; ip-keyed get/get_by_ips removed; list_enabled/list_disabled have no python post-filter (list_disabled filters ip <> '' in SQL)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.11.1 - task-schema-and-entity-cleanup: _row_to_task reads created_at/updated_at via row["created_at"]/row["updated_at"] (direct access — DB NOT NULL, was row.get() returning Any|None).
#   PREVIOUS_CHANGE: v1.11.0 - task-schema-and-entity-cleanup: _row_to_task reads title (renamed from label) → Task.label, reads status via TaskStatus[row["status"]] (name lookup, was int cast — pg8000 returns the enum label as a str), reads created_at/updated_at, drops the allocated_ip read (column dropped). save/insert bind :title (was :label, value is task.label/new_task.label), :status as status.name (enum-label string, was status.value int), drop :ip. list_by_status passes [s.name for s in statuses] (was [s.value for s in statuses]) with cast(:statuses AS task_status[]) (was int[]). count_by_status uses TaskStatus[row["status"]] (name lookup). list_ids_by_ip_and_status → list_ids_by_node_id_and_status (binds :node_id=node_id.value, :status=status.name; runs task/get_ids_by_node_id_and_status.sql). update_status passes status=status.name (was status.value).
#   PREVIOUS_CHANGE: v1.10.0 - ssh-rekey-node-id: PostgresNodeRepository removes get(ip) and get_by_ips(ips) (no caller resolves a node by ip) and adds get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node] (batch lookup, runs node/get_by_ids.sql with WHERE node_id = ANY(:node_ids), binds [n.value for n in node_ids]). node/get_by_ip.sql and node/get_by_ips.sql removed from the SQL layout; node/get_by_ids.sql added. get_by_id/list_*/insert/update/enable/disable/remove unchanged.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from yascheduler.domain import (
    NewNode,
    NewTask,
    Node,
    NodeId,
    Task,
    TaskContext,
    TaskId,
    TaskStatus,
)

from .exceptions import TaskRowNotFoundError
from .sql_loader import load_query

if TYPE_CHECKING:
    from collections.abc import Mapping
    from concurrent.futures import ThreadPoolExecutor

    from pg8000.native import Connection


class _PgRepository:
    """Base for pg8000-backed repositories — holds connection, executor."""

    def __init__(self, conn: Connection, executor: ThreadPoolExecutor) -> None:
        self._conn = conn
        self._executor = executor

    # START_CONTRACT: _run
    #   PURPOSE: Execute SQL via thread pool and return rows as dicts keyed by column name.
    #   INPUTS: { sql: str - query with :named params, **params: Any }
    #   OUTPUTS: { list[dict[str, Any]] - each row as a dict }
    #   SIDE_EFFECTS: None
    #   LINKS: None
    # END_CONTRACT: _run
    async def _run(self, sql: str, **params: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        """Execute SQL via the thread pool and return rows as dicts keyed by column name."""

        def _fn() -> list[dict[str, Any]]:
            rows: list[tuple[Any, ...]] = self._conn.run(sql, **params) or []
            cols = [c["name"] for c in (self._conn.columns or [])]
            return [dict(zip(cols, row)) for row in rows]

        return await asyncio.get_running_loop().run_in_executor(self._executor, _fn)


# START_CONTRACT: PostgresTaskRepository
#   PURPOSE: Async task CRUD using pg8000 Connection dispatched via ThreadPoolExecutor.
#   INPUTS: { conn: Connection - pg8000 native connection, executor: ThreadPoolExecutor }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Captures asyncio event loop at init for run_in_executor dispatch; tracks saved tasks for event collection.
#   LINKS: M-PERSISTENCE-SQLLOADER, M-DOMAIN-MODEL
# END_CONTRACT: PostgresTaskRepository
class PostgresTaskRepository(_PgRepository):
    """PostgreSQL implementation of TaskRepository port."""

    def __init__(
        self,
        conn: Connection,
        executor: ThreadPoolExecutor,
        saved_tasks: list[Task] | None = None,
    ) -> None:
        super().__init__(conn, executor)
        self._saved_tasks = saved_tasks

    # START_CONTRACT: get
    #   PURPOSE: Fetch a single task by its primary key.
    #   INPUTS: { task_id: TaskId - the primary-key value object }
    #   OUTPUTS: { Task | None - the task or None if not found }
    #   SIDE_EFFECTS: None
    #   LINKS: task/get_by_id.sql, _row_to_task
    # END_CONTRACT: get
    async def get(self, task_id: TaskId) -> Task | None:
        """Retrieve a task by ID, or None if not found.

        Passes ``task_id.value`` (the bare int) as the SQL param — pg8000 cannot
        adapt a ``TaskId`` dataclass.
        """
        rows = await self._run(load_query("task/get_by_id"), task_id=task_id.value)
        if not rows:
            return None
        return self._row_to_task(rows[0])

    # START_CONTRACT: save
    #   PURPOSE: Update mutable fields of an existing task row by task_id; raise TaskRowNotFoundError if the row does not exist.
    #   INPUTS: { task: Task - domain task with serialized context (task.task_id: TaskId) }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Writes to yascheduler_tasks row (SQL param task_id=task.task_id.value); binds allocated_node_id via :node_id (task.allocated_node_id.value or None); title carries task.label (DB column is title); status binds task.status.name (enum-label string); metadata serialized as JSON; raises TaskRowNotFoundError BEFORE appending to _saved_tasks when the targeted task_id does not exist. The BEFORE UPDATE trigger sets updated_at on the row.
    #   LINKS: task/update_by_id.sql, TaskContext.to_metadata, TaskRowNotFoundError
    # END_CONTRACT: save
    async def save(self, task: Task) -> None:
        """Persist task state to the database (update by task_id; raises on missing row)."""
        metadata = json.dumps(task.context.to_metadata())
        # START_BLOCK_DETECT_ZERO_ROWS
        rows = await self._run(
            load_query("task/update_by_id"),
            task_id=task.task_id.value,
            title=task.label,
            status=task.status.name,
            metadata=metadata,
            node_id=task.allocated_node_id.value if task.allocated_node_id else None,
        )
        if not rows:
            raise TaskRowNotFoundError(task.task_id)
        # END_BLOCK_DETECT_ZERO_ROWS
        if self._saved_tasks is not None:
            self._saved_tasks.append(task)

    # START_CONTRACT: update_status
    #   PURPOSE: Atomically update only the status field of a task; raise TaskRowNotFoundError if the row does not exist.
    #   INPUTS: { task_id: TaskId - task to update, status: TaskStatus - new status }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Executes atomic UPDATE on yascheduler_tasks.status (SQL param task_id=task_id.value, status=status.name — the enum-label string); raises TaskRowNotFoundError when the targeted task_id does not exist.
    #   LINKS: task/update_status.sql, TaskRowNotFoundError
    # END_CONTRACT: update_status
    async def update_status(self, task_id: TaskId, status: TaskStatus) -> None:
        """Atomically update only the status field; raises on missing row."""
        # START_BLOCK_DETECT_ZERO_ROWS
        rows = await self._run(
            load_query("task/update_status"),
            task_id=task_id.value,
            status=status.name,
        )
        if not rows:
            raise TaskRowNotFoundError(task_id)
        # END_BLOCK_DETECT_ZERO_ROWS

    # START_CONTRACT: list_ids_by_node_id_and_status
    #   PURPOSE: Return task IDs allocated to the given node and matching the given status.
    #   INPUTS: { node_id: NodeId - the node identity (allocated_node_id filter), status: TaskStatus }
    #   OUTPUTS: { list[TaskId] - task IDs (the caller feeds them to update_status(TaskId, ...)) }
    #   SIDE_EFFECTS: None
    #   LINKS: task/get_ids_by_node_id_and_status.sql
    # END_CONTRACT: list_ids_by_node_id_and_status
    async def list_ids_by_node_id_and_status(
        self, node_id: NodeId, status: TaskStatus
    ) -> list[TaskId]:
        """Return task IDs allocated to the given node and matching the status."""
        rows = await self._run(
            load_query("task/get_ids_by_node_id_and_status"),
            node_id=node_id.value,
            status=status.name,
        )
        return [TaskId(int(row["task_id"])) for row in rows]

    # START_CONTRACT: insert
    #   PURPOSE: Insert a new task row and return a Task with the DB-generated task_id (sole NewTask→Task conversion).
    #   INPUTS: { new_task: NewTask - pre-persistence task record (no task_id; the DB generates it) }
    #   OUTPUTS: { Task - the newly created task carrying the generated TaskId, created_at, updated_at }
    #   SIDE_EFFECTS: Inserts row into yascheduler_tasks; assigns task_id via RETURNING; binds allocated_node_id via :node_id (new_task.allocated_node_id.value or None); title carries new_task.label; status binds new_task.status.name (enum-label string); created_at/updated_at populated by DEFAULT NOW() (not bound) and read back via RETURNING.
    #   LINKS: task/insert.sql, _row_to_task
    # END_CONTRACT: insert
    async def insert(self, new_task: NewTask) -> Task:
        """Insert a NewTask, return the persisted Task with the generated ID."""
        metadata = json.dumps(new_task.context.to_metadata())
        rows = await self._run(
            load_query("task/insert"),
            title=new_task.label,
            metadata=metadata,
            status=new_task.status.name,
            node_id=(
                new_task.allocated_node_id.value if new_task.allocated_node_id else None
            ),
        )
        return self._row_to_task(rows[0])

    # START_CONTRACT: list_by_status
    #   PURPOSE: Query tasks filtered by a set of status values.
    #   INPUTS: { statuses: set[TaskStatus], limit: int | None }
    #   OUTPUTS: { list[Task] - tasks matching any of the given statuses }
    #   SIDE_EFFECTS: None
    #   LINKS: task/list_by_status.sql, _row_to_task
    # END_CONTRACT: list_by_status
    async def list_by_status(
        self, statuses: set[TaskStatus], limit: int | None = None
    ) -> list[Task]:
        """Return tasks matching any of the given statuses."""
        rows = await self._run(
            load_query("task/list_by_status"),
            statuses=[s.name for s in statuses],
            lim=limit,
        )
        return [self._row_to_task(r) for r in rows]

    # START_CONTRACT: list_by_jobs
    #   PURPOSE: Query tasks by a list of task IDs (used by Yascheduler client facade).
    #   INPUTS: { job_ids: list[TaskId] - task IDs to look up }
    #   OUTPUTS: { list[Task] - tasks carrying TaskId }
    #   SIDE_EFFECTS: None
    #   LINKS: task/list_by_jobs.sql, _row_to_task
    # END_CONTRACT: list_by_jobs
    async def list_by_jobs(self, job_ids: list[TaskId]) -> list[Task]:
        """Return tasks whose IDs are in the given list."""
        rows = await self._run(
            load_query("task/list_by_jobs"), task_ids=[tid.value for tid in job_ids]
        )
        return [self._row_to_task(r) for r in rows]

    # START_CONTRACT: count_by_status
    #   PURPOSE: Aggregate task counts grouped by status.
    #   INPUTS: { None }
    #   OUTPUTS: { Mapping[TaskStatus, int] - keys via name lookup TaskStatus[row["status"]] (pg8000 returns the enum label as a str) }
    #   SIDE_EFFECTS: None
    #   LINKS: task/count_by_status.sql
    # END_CONTRACT: count_by_status
    async def count_by_status(self) -> Mapping[TaskStatus, int]:
        """Return a mapping of TaskStatus to task count."""
        rows = await self._run(load_query("task/count_by_status"))
        return {TaskStatus[row["status"]]: row["count"] for row in rows}

    # START_CONTRACT: _row_to_task
    #   PURPOSE: Map a DB row dict to a domain Task, parsing JSONB metadata and wrapping TaskId from the task_id column and NodeId from the allocated_node_id column.
    #   INPUTS: { row: dict[str, Any] - row with keys task_id, title, status, metadata, allocated_node_id, created_at, updated_at }
    #   OUTPUTS: { Task - carries task_id: TaskId, allocated_node_id: NodeId | None, created_at/updated_at: datetime (DB NOT NULL DEFAULT NOW()), label=row["title"] }
    #   SIDE_EFFECTS: None
    #   LINKS: TaskContext.from_metadata, TaskId, NodeId
    # END_CONTRACT: _row_to_task
    @staticmethod
    def _row_to_task(row: dict[str, Any]) -> Task:
        """Convert a DB row dict to a domain Task."""
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        elif not isinstance(metadata, dict):
            metadata = {}
        ctx = TaskContext.from_metadata(metadata)
        # Events are transient — always empty when loaded from DB.
        allocated_node_id_raw = row.get("allocated_node_id")
        return Task(
            task_id=TaskId(int(row["task_id"])),
            label=row.get("title", ""),
            context=ctx,
            status=TaskStatus[row["status"]],
            allocated_node_id=(
                NodeId(int(allocated_node_id_raw))
                if allocated_node_id_raw is not None
                else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# START_CONTRACT: PostgresNodeRepository
#   PURPOSE: Async node CRUD using pg8000 Connection dispatched via ThreadPoolExecutor.
#   INPUTS: { conn: Connection - pg8000 native connection, executor: ThreadPoolExecutor }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Captures asyncio event loop at init for run_in_executor dispatch.
#   LINKS: M-PERSISTENCE-SQLLOADER, M-DOMAIN-MODEL
# END_CONTRACT: PostgresNodeRepository
class PostgresNodeRepository(_PgRepository):
    """PostgreSQL implementation of NodeRepository port.

    ``insert(new_node: NewNode) -> Node`` is the sole node-insertion path
    (``add_tmp`` is removed); the tmp-reservation flow calls
    ``insert(NewNode(cloud=..., enabled=False))``. ``list_enabled`` and
    ``list_disabled`` have no python post-filter — by the invariant
    (``ip == ''`` IFF ``enabled = FALSE`` AND the node is tmp/pending), no
    enabled row has ``ip == ""`` (so the prior ``"." in r["ip"]`` filter was
    dead in ``list_enabled``); ``list_disabled`` filters ``ip <> ''`` in SQL
    (``node/list_disabled.sql``) so tmp rows are excluded at the DB layer.
    """

    # START_CONTRACT: list_all
    #   PURPOSE: Return all nodes without filtering.
    #   INPUTS: { None }
    #   OUTPUTS: { list[Node] }
    #   SIDE_EFFECTS: None
    #   LINKS: node/list_all.sql, _row_to_node
    # END_CONTRACT: list_all
    async def list_all(self) -> list[Node]:
        """Return all nodes."""
        rows = await self._run(load_query("node/list_all"))
        return [self._row_to_node(r) for r in rows]

    # START_CONTRACT: list_enabled
    #   PURPOSE: Return enabled nodes (WHERE enabled = TRUE; no python post-filter — by the invariant enabled=TRUE ⇒ ip<>'').
    #   INPUTS: { None }
    #   OUTPUTS: { list[Node] }
    #   SIDE_EFFECTS: None
    #   LINKS: node/list_enabled.sql, _row_to_node
    # END_CONTRACT: list_enabled
    async def list_enabled(self) -> list[Node]:
        """Return enabled nodes (SQL WHERE enabled = TRUE is the only filter)."""
        rows = await self._run(load_query("node/list_enabled"))
        return [self._row_to_node(r) for r in rows]

    # START_CONTRACT: list_disabled
    #   PURPOSE: Return disabled nodes with a real IP (WHERE enabled = FALSE AND ip <> ''; the ip <> '' presence check excludes tmp rows at the SQL layer — no python post-filter).
    #   INPUTS: { None }
    #   OUTPUTS: { list[Node] }
    #   SIDE_EFFECTS: None
    #   LINKS: node/list_disabled.sql, _row_to_node
    # END_CONTRACT: list_disabled
    async def list_disabled(self) -> list[Node]:
        """Return disabled nodes with a real IP (filter is in SQL, not python)."""
        rows = await self._run(load_query("node/list_disabled"))
        return [self._row_to_node(r) for r in rows]

    # START_CONTRACT: insert
    #   PURPOSE: Persist a NewNode and return the persisted Node with the DB-generated NodeId (sole node-insertion path — add_tmp removed).
    #   INPUTS: { new_node: NewNode - pre-persistence node record (no node_id); serves the tmp-reservation path when called as NewNode(cloud=..., enabled=False) }
    #   OUTPUTS: { Node - the persisted node carrying the generated NodeId and matching the NewNode's other fields }
    #   SIDE_EFFECTS: Inserts row into yascheduler_nodes; assigns node_id via RETURNING node_id.
    #   LINKS: node/insert.sql RETURNING node_id, _row_to_node
    # END_CONTRACT: insert
    async def insert(self, new_node: NewNode) -> Node:
        """Insert a NewNode, return the persisted Node with the generated NodeId."""
        rows = await self._run(
            load_query("node/insert"),
            ip=new_node.ip,
            ncpus=new_node.ncpus,
            enabled=new_node.enabled,
            cloud=new_node.cloud,
            username=new_node.username,
            port=new_node.port,
        )
        # RETURNING node_id yields a single row; _row_to_node reads node_id and
        # rebuilds the full Node from it + the input fields (the only columns
        # the RETURNING clause emits is node_id, so fall back to new_node values
        # for the non-returned fields).
        row = {
            **rows[0],
            "ip": new_node.ip,
            "ncpus": new_node.ncpus,
            "enabled": new_node.enabled,
            "cloud": new_node.cloud,
            "username": new_node.username,
            "port": new_node.port,
        }
        return self._row_to_node(row)

    # START_CONTRACT: get_by_id
    #   PURPOSE: Fetch a single node by its primary key.
    #   INPUTS: { node_id: NodeId - the primary-key value object }
    #   OUTPUTS: { Node | None - the node, or None if no row matches }
    #   SIDE_EFFECTS: None
    #   LINKS: node/get_by_id.sql, _row_to_node
    # END_CONTRACT: get_by_id
    async def get_by_id(self, node_id: NodeId) -> Node | None:
        """Retrieve a node by primary key, or None if not found.

        Passes ``node_id.value`` (the bare int) as the SQL param — pg8000 cannot
        adapt a ``NodeId`` dataclass.
        """
        rows = await self._run(load_query("node/get_by_id"), node_id=node_id.value)
        if not rows:
            return None
        return self._row_to_node(rows[0])

    # START_CONTRACT: get_by_ids
    #   PURPOSE: Batch-lookup nodes by primary-key list, returning a dict keyed by NodeId.
    #   INPUTS: { node_ids: list[NodeId] - primary keys to look up }
    #   OUTPUTS: { dict[NodeId, Node] - nodes keyed by NodeId; missing node_ids are absent from the dict }
    #   SIDE_EFFECTS: None
    #   LINKS: node/get_by_ids.sql, _row_to_node
    # END_CONTRACT: get_by_ids
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

    # START_CONTRACT: update
    #   PURPOSE: Persist all mutable node fields by node_id via UPDATE.
    #   INPUTS: { node: Node - carries node_id (used as the WHERE key) and the fields to set }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Updates yascheduler_nodes row (WHERE node_id = :node_id).
    #   LINKS: node/update.sql
    # END_CONTRACT: update
    async def update(self, node: Node) -> None:
        """Persist all mutable node fields by node_id."""
        await self._run(
            load_query("node/update"),
            node_id=node.node_id.value,
            ip=node.ip,
            ncpus=node.ncpus,
            enabled=node.enabled,
            cloud=node.cloud,
            username=node.username,
            port=node.port,
        )

    # START_CONTRACT: enable
    #   PURPOSE: Set a node's enabled flag to TRUE by node_id.
    #   INPUTS: { node_id: NodeId - the primary-key value object }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Updates yascheduler_nodes.enabled (WHERE node_id = :node_id).
    #   LINKS: node/enable.sql
    # END_CONTRACT: enable
    async def enable(self, node_id: NodeId) -> None:
        """Enable a node by node_id (passes node_id.value — pg8000 cannot adapt a NodeId)."""
        await self._run(load_query("node/enable"), node_id=node_id.value)

    # START_CONTRACT: disable
    #   PURPOSE: Set a node's enabled flag to FALSE by node_id.
    #   INPUTS: { node_id: NodeId - the primary-key value object }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Updates yascheduler_nodes.enabled (WHERE node_id = :node_id).
    #   LINKS: node/disable.sql
    # END_CONTRACT: disable
    async def disable(self, node_id: NodeId) -> None:
        """Disable a node by node_id (passes node_id.value — pg8000 cannot adapt a NodeId)."""
        await self._run(load_query("node/disable"), node_id=node_id.value)

    # START_CONTRACT: remove
    #   PURPOSE: Delete a node row by node_id.
    #   INPUTS: { node_id: NodeId - the primary-key value object }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Deletes row from yascheduler_nodes (WHERE node_id = :node_id).
    #   LINKS: node/remove.sql
    # END_CONTRACT: remove
    async def remove(self, node_id: NodeId) -> None:
        """Delete a node by node_id (passes node_id.value — pg8000 cannot adapt a NodeId)."""
        await self._run(load_query("node/remove"), node_id=node_id.value)

    # START_CONTRACT: count_by_cloud
    #   PURPOSE: Aggregate node counts grouped by cloud provider.
    #   INPUTS: { None }
    #   OUTPUTS: { Mapping[str, int] }
    #   SIDE_EFFECTS: None
    #   LINKS: node/count_by_cloud.sql
    # END_CONTRACT: count_by_cloud
    async def count_by_cloud(self) -> Mapping[str, int]:
        """Return a mapping of cloud provider to node count."""
        rows = await self._run(load_query("node/count_by_cloud"))
        return {row["cloud"]: row["count"] for row in rows}

    # START_CONTRACT: count_by_status
    #   PURPOSE: Aggregate node counts grouped by enabled/disabled status.
    #   INPUTS: { None }
    #   OUTPUTS: { Mapping[bool, int] }
    #   SIDE_EFFECTS: None
    #   LINKS: node/count_by_status.sql
    # END_CONTRACT: count_by_status
    async def count_by_status(self) -> Mapping[bool, int]:
        """Return a mapping of enabled (bool) to node count."""
        rows = await self._run(load_query("node/count_by_status"))
        return {bool(row["enabled"]): row["count"] for row in rows}

    # START_CONTRACT: _row_to_node
    #   PURPOSE: Map a DB row dict to a domain Node, wrapping NodeId from the node_id column.
    #   INPUTS: { row: dict[str, Any] - row with keys node_id, ip, ncpus, enabled, cloud, username, port }
    #   OUTPUTS: { Node - carries node_id: NodeId }
    #   SIDE_EFFECTS: None
    #   LINKS: Node, NodeId
    # END_CONTRACT: _row_to_node
    @staticmethod
    def _row_to_node(row: dict[str, Any]) -> Node:
        """Convert a DB row dict to a domain Node."""
        return Node(
            node_id=NodeId(int(row["node_id"])),
            ip=row["ip"],
            ncpus=row.get("ncpus") or 0,
            enabled=bool(row.get("enabled", False)),
            cloud=row.get("cloud"),
            username=row.get("username", "root"),
            port=row.get("port", 22),
        )
