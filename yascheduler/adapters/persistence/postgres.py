# FILE: yascheduler/adapters/persistence/postgres.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: PostgreSQL repository implementations for tasks and nodes.
#   SCOPE: _PgRepository base, PostgresTaskRepository and PostgresNodeRepository wrappers around pg8000 Connection.
#   DEPENDS: M-PERSISTENCE-SQLLOADER, M-DOMAIN-MODEL, M-DOMAIN-PORTS
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-PERSISTENCE-SQLLOADER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _PgRepository - base class for pg8000-backed repositories (conn, executor, _run)
#   PostgresTaskRepository - async task CRUD: get, save, update_status, insert, list_by_status, list_by_jobs, count_by_status
#   PostgresNodeRepository - async node CRUD: get, get_by_ips, list_*, add, add_tmp, enable, disable, remove, count_*
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - Refactor _run, _row_to_task, _row_to_node to use dict-based row mapping.
#   PREVIOUS_CHANGE: v1.3.0 - Extract _PgRepository base; implement node update() with UPDATE SQL.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pg8000.native import Connection

from ...domain.model import Node, Task, TaskContext, TaskStatus
from . import load_query


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
    async def _run(self, sql: str, **params: Any) -> list[dict[str, Any]]:
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
#   SIDE_EFFECTS: Captures asyncio event loop at init for run_in_executor dispatch.
#   LINKS: M-PERSISTENCE-SQLLOADER, M-DOMAIN-MODEL
# END_CONTRACT: PostgresTaskRepository
class PostgresTaskRepository(_PgRepository):
    """PostgreSQL implementation of TaskRepository port."""

    # START_CONTRACT: get
    #   PURPOSE: Fetch a single task by its database ID.
    #   INPUTS: { task_id: int }
    #   OUTPUTS: { Task | None - the task or None if not found }
    #   SIDE_EFFECTS: None
    #   LINKS: task/get_by_id.sql, _row_to_task
    # END_CONTRACT: get
    async def get(self, task_id: int) -> Task | None:
        """Retrieve a task by ID, or None if not found."""
        rows = await self._run(load_query("task/get_by_id"), task_id=task_id)
        if not rows:
            return None
        return self._row_to_task(rows[0])

    # START_CONTRACT: save
    #   PURPOSE: Upsert all mutable task fields (label, status, ip, metadata) by task_id.
    #   INPUTS: { task: Task - domain task with serialized context }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Writes to yascheduler_tasks row; metadata serialized as JSON.
    #   LINKS: task/upsert.sql, TaskContext.to_metadata
    # END_CONTRACT: save
    async def save(self, task: Task) -> None:
        """Persist task state to the database (upsert by task_id)."""
        metadata = json.dumps(task.context.to_metadata())
        await self._run(
            load_query("task/upsert"),
            task_id=task.task_id,
            label=task.label,
            status=task.status.value,
            ip=task.allocated_ip,
            metadata=metadata,
        )

    # START_CONTRACT: update_status
    #   PURPOSE: Atomically update only the status field of a task.
    #   INPUTS: { task_id: int - task to update, status: TaskStatus - new status }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Executes atomic UPDATE on yascheduler_tasks.status.
    #   LINKS: task/update_status.sql
    # END_CONTRACT: update_status
    async def update_status(self, task_id: int, status: TaskStatus) -> None:
        """Atomically update only the status field."""
        await self._run(
            load_query("task/update_status"),
            task_id=task_id,
            status=status.value,
        )

    # START_CONTRACT: list_ids_by_ip_and_status
    #   PURPOSE: Return task IDs matching the given IP and status.
    #   INPUTS: { ip: str, status: TaskStatus }
    #   OUTPUTS: { list[int] - task IDs }
    #   SIDE_EFFECTS: None
    #   LINKS: task/get_ids_by_ip_and_status.sql
    # END_CONTRACT: list_ids_by_ip_and_status
    async def list_ids_by_ip_and_status(self, ip: str, status: TaskStatus) -> list[int]:
        """Return task IDs matching the given IP and status."""
        rows = await self._run(
            load_query("task/get_ids_by_ip_and_status"),
            ip=ip,
            status=status.value,
        )
        return [row["task_id"] for row in rows]

    # START_CONTRACT: insert
    #   PURPOSE: Insert a new task row and return a Task with the generated task_id.
    #   INPUTS: { task: Task - domain task (task_id is ignored, generated by DB) }
    #   OUTPUTS: { Task - the newly created task with real task_id }
    #   SIDE_EFFECTS: Inserts row into yascheduler_tasks; assigns task_id via RETURNING.
    #   LINKS: task/insert.sql, _row_to_task
    # END_CONTRACT: insert
    async def insert(self, task: Task) -> Task:
        """Insert a new task, return it with the generated ID."""
        metadata = json.dumps(task.context.to_metadata())
        rows = await self._run(
            load_query("task/insert"),
            label=task.label,
            metadata=metadata,
            ip=task.allocated_ip,
            status=task.status.value,
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
            statuses=[s.value for s in statuses],
            lim=limit,
        )
        return [self._row_to_task(r) for r in rows]

    # START_CONTRACT: list_by_jobs
    #   PURPOSE: Query tasks by a list of task IDs (used by Yascheduler client facade).
    #   INPUTS: { job_ids: list[int] }
    #   OUTPUTS: { list[Task] }
    #   SIDE_EFFECTS: None
    #   LINKS: task/list_by_jobs.sql, _row_to_task
    # END_CONTRACT: list_by_jobs
    async def list_by_jobs(self, job_ids: list[int]) -> list[Task]:
        """Return tasks whose IDs are in the given list."""
        rows = await self._run(load_query("task/list_by_jobs"), task_ids=job_ids)
        return [self._row_to_task(r) for r in rows]

    # START_CONTRACT: count_by_status
    #   PURPOSE: Aggregate task counts grouped by status.
    #   INPUTS: { None }
    #   OUTPUTS: { Mapping[TaskStatus, int] }
    #   SIDE_EFFECTS: None
    #   LINKS: task/count_by_status.sql
    # END_CONTRACT: count_by_status
    async def count_by_status(self) -> Mapping[TaskStatus, int]:
        """Return a mapping of TaskStatus to task count."""
        rows = await self._run(load_query("task/count_by_status"))
        return {TaskStatus(row["status"]): row["count"] for row in rows}

    # START_CONTRACT: _row_to_task
    #   PURPOSE: Map a DB row dict to a domain Task, parsing JSONB metadata.
    #   INPUTS: { row: dict[str, Any] - row with keys task_id, label, ip, status, metadata }
    #   OUTPUTS: { Task }
    #   SIDE_EFFECTS: None
    #   LINKS: TaskContext.from_metadata
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
        return Task(
            task_id=row["task_id"],
            label=row.get("label", ""),
            context=ctx,
            status=TaskStatus(row["status"]),
            allocated_ip=row.get("ip") or None,
        )


# START_CONTRACT: PostgresNodeRepository
#   PURPOSE: Async node CRUD using pg8000 Connection dispatched via ThreadPoolExecutor.
#   INPUTS: { conn: Connection - pg8000 native connection, executor: ThreadPoolExecutor }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Captures asyncio event loop at init for run_in_executor dispatch.
#   LINKS: M-PERSISTENCE-SQLLOADER, M-DOMAIN-MODEL
# END_CONTRACT: PostgresNodeRepository
class PostgresNodeRepository(_PgRepository):
    """PostgreSQL implementation of NodeRepository port."""

    # START_CONTRACT: get
    #   PURPOSE: Fetch a single node by IP address.
    #   INPUTS: { ip: str }
    #   OUTPUTS: { Node | None }
    #   SIDE_EFFECTS: None
    #   LINKS: node/get_by_ip.sql, _row_to_node
    # END_CONTRACT: get
    async def get(self, ip: str) -> Node | None:
        """Retrieve a node by IP, or None if not found."""
        rows = await self._run(load_query("node/get_by_ip"), ip=ip)
        if not rows:
            return None
        return self._row_to_node(rows[0])

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
    #   PURPOSE: Return enabled nodes with valid IPs (containing ".").
    #   INPUTS: { None }
    #   OUTPUTS: { list[Node] }
    #   SIDE_EFFECTS: None
    #   LINKS: node/list_enabled.sql, _row_to_node
    # END_CONTRACT: list_enabled
    async def list_enabled(self) -> list[Node]:
        """Return enabled nodes (post-filtered for valid IPs)."""
        rows = await self._run(load_query("node/list_enabled"))
        return [self._row_to_node(r) for r in rows if "." in r["ip"]]

    # START_CONTRACT: list_disabled
    #   PURPOSE: Return disabled nodes with valid IPs (containing ".").
    #   INPUTS: { None }
    #   OUTPUTS: { list[Node] }
    #   SIDE_EFFECTS: None
    #   LINKS: node/list_disabled.sql, _row_to_node
    # END_CONTRACT: list_disabled
    async def list_disabled(self) -> list[Node]:
        """Return disabled nodes (post-filtered for valid IPs)."""
        rows = await self._run(load_query("node/list_disabled"))
        return [self._row_to_node(r) for r in rows if "." in r["ip"]]

    # START_CONTRACT: add
    #   PURPOSE: Insert a new persistent node row.
    #   INPUTS: { node: Node }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Inserts row into yascheduler_nodes.
    #   LINKS: node/insert.sql
    # END_CONTRACT: add
    async def add(self, node: Node) -> None:
        """Insert a new node."""
        await self._run(
            load_query("node/insert"),
            ip=node.ip,
            ncpus=node.ncpus,
            enabled=node.enabled,
            cloud=node.cloud,
            username=node.username,
            port=node.port,
        )

    # START_CONTRACT: add_tmp
    #   PURPOSE: Insert a temporary cloud node with a generated IP, return the IP.
    #   INPUTS: { cloud: str, username: str = "root" }
    #   OUTPUTS: { str - the generated IP }
    #   SIDE_EFFECTS: Inserts row into yascheduler_nodes with enabled=FALSE.
    #   LINKS: node/insert_tmp.sql
    # END_CONTRACT: add_tmp
    async def add_tmp(self, cloud: str, username: str = "root") -> str:
        """Insert a temp cloud node with generated IP, return the IP."""
        rows = await self._run(
            load_query("node/insert_tmp"), cloud=cloud, username=username
        )
        return rows[0]["ip"]

    # START_CONTRACT: get_by_ips
    #   PURPOSE: Return nodes keyed by IP for the given IP list (batch lookup).
    #   INPUTS: { ips: list[str] - list of IPs to fetch }
    #   OUTPUTS: { dict[str, Node] - nodes keyed by IP }
    #   SIDE_EFFECTS: None
    #   LINKS: node/get_by_ips.sql, _row_to_node
    # END_CONTRACT: get_by_ips
    async def get_by_ips(self, ips: list[str]) -> dict[str, Node]:
        """Return nodes keyed by IP for the given IP list."""
        rows = await self._run(
            load_query("node/get_by_ips"),
            ips=ips,
        )
        return {row["ip"]: self._row_to_node(row) for row in rows}

    # START_CONTRACT: update
    #   PURPOSE: Persist all mutable node fields by IP via UPDATE.
    #   INPUTS: { node: Node }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Updates yascheduler_nodes row.
    #   LINKS: node/update.sql
    # END_CONTRACT: update
    async def update(self, node: Node) -> None:
        """Persist all mutable node fields by IP."""
        await self._run(
            load_query("node/update"),
            ip=node.ip,
            ncpus=node.ncpus,
            enabled=node.enabled,
            cloud=node.cloud,
            username=node.username,
            port=node.port,
        )

    # START_CONTRACT: enable
    #   PURPOSE: Set a node's enabled flag to TRUE.
    #   INPUTS: { ip: str }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Updates yascheduler_nodes.enabled.
    #   LINKS: node/enable.sql
    # END_CONTRACT: enable
    async def enable(self, ip: str) -> None:
        """Enable a node by IP."""
        await self._run(load_query("node/enable"), ip=ip)

    # START_CONTRACT: disable
    #   PURPOSE: Set a node's enabled flag to FALSE.
    #   INPUTS: { ip: str }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Updates yascheduler_nodes.enabled.
    #   LINKS: node/disable.sql
    # END_CONTRACT: disable
    async def disable(self, ip: str) -> None:
        """Disable a node by IP."""
        await self._run(load_query("node/disable"), ip=ip)

    # START_CONTRACT: remove
    #   PURPOSE: Delete a node row by IP.
    #   INPUTS: { ip: str }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Deletes row from yascheduler_nodes.
    #   LINKS: node/remove.sql
    # END_CONTRACT: remove
    async def remove(self, ip: str) -> None:
        """Delete a node by IP."""
        await self._run(load_query("node/remove"), ip=ip)

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
    #   PURPOSE: Map a DB row dict to a domain Node.
    #   INPUTS: { row: dict[str, Any] - row with keys ip, ncpus, enabled, cloud, username, port }
    #   OUTPUTS: { Node }
    #   SIDE_EFFECTS: None
    #   LINKS: Node
    # END_CONTRACT: _row_to_node
    @staticmethod
    def _row_to_node(row: dict[str, Any]) -> Node:
        """Convert a DB row dict to a domain Node."""
        return Node(
            ip=row["ip"],
            ncpus=row.get("ncpus") or 0,
            enabled=bool(row.get("enabled", False)),
            cloud=row.get("cloud"),
            username=row.get("username", "root"),
            port=row.get("port", 22),
        )
