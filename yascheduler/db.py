# FILE: yascheduler/db.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: PostgreSQL persistence for tasks, nodes, and their statuses.
#   SCOPE: Task and node CRUD, status transitions, schema migration.
#   DEPENDS: M-CONFIG-DB, M-COMPAT
#   LINKS: M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   DB: Database abstraction class with async methods for task/node CRUD and status transitions.
#   TaskModel: Immutable task data model (task_id, label, ip, status, metadata, cloud).
#   NodeModel: Immutable node data model (ip, ncpus, enabled, cloud, username, port).
#   TaskStatus: IntEnum of possible task states (TO_DO, RUNNING, DONE).
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

"""Database utils"""

import asyncio
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, unique
from typing import Any, Optional, cast

import backoff
from attrs import asdict, define, field
from pg8000.native import Connection, InterfaceError

from .compat import Self
from .config import ConfigDb


@unique
class TaskStatus(int, Enum):
    """Task possible states enum"""

    TO_DO = 0
    RUNNING = 1
    DONE = 2


@define(frozen=True, hash=True)
class NodeModel:
    """Node model"""

    ip: str = field()
    ncpus: Optional[int] = field()
    enabled: bool = field(default=True)
    cloud: Optional[str] = field(default=None)
    username: str = field(default="root")
    port: int = field(default=22)


@define(frozen=True)
class TaskModel:
    """Task model"""

    task_id: int = field()
    label: str = field()
    ip: str = field()
    status: TaskStatus = field(converter=TaskStatus)
    metadata: Mapping[str, Any] = field(factory=dict)
    cloud: Optional[str] = field(default=None)

    def __hash__(self) -> int:
        return hash(json.dumps(asdict(self), sort_keys=True))


@define(frozen=True)
class DB:
    """Database abstraction"""

    loop: asyncio.AbstractEventLoop = field()
    executor: ThreadPoolExecutor = field()
    conn: Connection = field()

    @staticmethod
    def create_connection(config: ConfigDb) -> Connection:
        """Create database connection"""
        return Connection(
            user=config.user,
            host=config.host,
            database=config.database,
            port=config.port,
            password=config.password,
        )

    # START_CONTRACT: create
    #   PURPOSE: Async factory to create DB instance with optional auto-migration
    #   INPUTS: { config: ConfigDb - database configuration, automigrate: bool - whether to run migrations on init (default True) }
    #   OUTPUTS: { Self - initialized DB instance with live connection }
    #   SIDE_EFFECTS: Creates DB connection; optionally runs schema migration
    #   LINKS: [M-DB]
    # END_CONTRACT: create
    @classmethod
    async def create(cls, config: ConfigDb, automigrate=True) -> Self:
        """Async init"""
        loop = asyncio.get_running_loop()
        exe = ThreadPoolExecutor(max_workers=1)  # pg8000 is not thread safe
        conn = await loop.run_in_executor(exe, cls.create_connection, config)
        ins = cls(loop=loop, executor=exe, conn=conn)
        if automigrate:
            await ins.migrate()
        return ins

    async def run(self, sql: str, **params):
        """Run query async with backoff"""

        @backoff.on_exception(backoff.fibo, InterfaceError, max_time=60)
        def run_fn():
            return self.conn.run(sql, **params)

        return await self.loop.run_in_executor(self.executor, run_fn)

    # START_CONTRACT: migrate
    #   PURPOSE: Run database schema migrations (add columns if not exist)
    #   INPUTS: { None }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Alters yascheduler_nodes table schema (adds username, port columns)
    #   LINKS: [M-DB]
    # END_CONTRACT: migrate
    async def migrate(self) -> None:
        """Migrate database scheme"""
        # START_BLOCK_CREATE_TABLES
        await self.run(
            """
            ALTER TABLE yascheduler_nodes
            ADD COLUMN IF NOT EXISTS username VARCHAR(255) DEFAULT 'root';
            ALTER TABLE yascheduler_nodes
            ADD COLUMN IF NOT EXISTS port INTEGER DEFAULT 22;
            """
        )
        # END_BLOCK_CREATE_TABLES

    async def commit(self):
        """Commit"""
        await self.run("COMMIT;")

    async def close(self):
        """Close connection"""
        await self.loop.run_in_executor(self.executor, self.conn.close)
        self.executor.shutdown()

    async def has_node(self, ip_addr: str) -> bool:
        """Check if node exist"""
        await self.run("SELECT ip FROM yascheduler_nodes WHERE ip=:ip;", ip=ip_addr)
        return bool(self.conn.row_count)

    async def update_task_status(self, task_id: int, status: TaskStatus) -> None:
        """Update task status"""
        await self.run(
            "UPDATE yascheduler_tasks SET status=:status WHERE task_id=:task_id;",
            task_id=task_id,
            status=status.value,
        )

    async def get_all_nodes(self) -> Sequence[NodeModel]:
        """Get all nodes"""
        rows = await self.run(
            """SELECT ip, ncpus, enabled, cloud, username, port FROM yascheduler_nodes;"""
        )
        return [NodeModel(*x) for x in (rows or [])]

    async def get_enabled_nodes(self) -> Sequence[NodeModel]:
        """Get all enabled nodes"""
        rows = await self.run(
            """SELECT ip, ncpus, enabled, cloud, username, port
            FROM yascheduler_nodes WHERE enabled=TRUE;"""
        )
        return [y for y in [NodeModel(*x) for x in (rows or [])] if "." in y.ip]

    async def get_disabled_nodes(self) -> Sequence[NodeModel]:
        """Get all disabled nodes"""
        rows = await self.run(
            """SELECT ip, ncpus, enabled, cloud, username, port
            FROM yascheduler_nodes WHERE enabled=FALSE;"""
        )
        return [y for y in [NodeModel(*x) for x in (rows or [])] if "." in y.ip]

    async def get_node(self, ip_addr: str) -> Optional[NodeModel]:
        """Get node by ip"""
        rows = await self.run(
            """SELECT ip, ncpus, enabled, cloud, username, port
            FROM yascheduler_nodes
            WHERE ip=:ip;""",
            ip=ip_addr,
        )
        for row in rows or []:
            return NodeModel(*row)

    async def count_nodes_clouds(self) -> Mapping[str, int]:
        """Count nodes in clouds"""
        rows = await self.run(
            """SELECT cloud, COUNT(cloud) FROM yascheduler_nodes
            WHERE cloud IS NOT NULL GROUP BY cloud;"""
        )
        data = {}
        for row in rows or []:
            data[row[0]] = row[1]
        return data

    async def count_nodes_by_status(self) -> Mapping[bool, int]:
        """Count nodes by status"""
        rows = await self.run(
            """SELECT enabled, COUNT(ip) FROM yascheduler_nodes
            GROUP BY enabled ORDER BY enabled;"""
        )
        data = defaultdict(int)
        for row in rows or []:
            data[bool(row[0])] = row[1]
        return data

    # START_CONTRACT: add_tmp_node
    #   PURPOSE: Add a temporary cloud-provisioned node with generated provisional IP
    #   INPUTS: { cloud: str - cloud provider name, username: str - SSH username for node }
    #   OUTPUTS: { str - generated provisional IP address }
    #   SIDE_EFFECTS: Inserts disabled node with provisional IP into yascheduler_nodes
    #   LINKS: [M-DB]
    # END_CONTRACT: add_tmp_node
    async def add_tmp_node(self, cloud: str, username: str) -> str:
        """Add temporary node"""
        rows = await self.run(
            """INSERT INTO yascheduler_nodes (ip, enabled, cloud, username)
            VALUES ('prov' || SUBSTR(MD5(RANDOM()::TEXT), 0, 11),
              FALSE, :cloud, :username)
            RETURNING ip;""",
            cloud=cloud,
            username=username,
        )
        rows = cast(list[list[str]], rows)
        return rows[0][0]

    # START_CONTRACT: add_node
    #   PURPOSE: Insert a new compute node record
    #   INPUTS: { ip_addr: str - node IP, username: str - SSH username, port: Optional[int] - SSH port (default 22), ncpus: Optional[int] - CPU count, cloud: Optional[str] - cloud provider name, enabled: bool - whether node is enabled (default False) }
    #   OUTPUTS: { NodeModel - newly created node data }
    #   SIDE_EFFECTS: Inserts row into yascheduler_nodes
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
        """Add new node"""
        port = port or 22
        # START_BLOCK_INSERT
        await self.run(
            """INSERT INTO yascheduler_nodes (ip, ncpus, enabled, cloud, username, port)
            VALUES (:ip, :ncpus, :enabled, :cloud, :username, :port);""",
            ip=ip_addr,
            ncpus=ncpus,
            cloud=cloud,
            username=username,
            enabled=enabled,
            port=port,
        )
        # END_BLOCK_INSERT
        return NodeModel(
            ip_addr,
            ncpus,
            enabled=enabled,
            cloud=cloud,
            username=username,
            port=port,
        )

    # START_CONTRACT: enable_node
    #   PURPOSE: Enable a node for task scheduling
    #   INPUTS: { ip_addr: str - node IP to enable }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Sets enabled=TRUE on the node
    #   LINKS: [M-DB]
    # END_CONTRACT: enable_node
    async def enable_node(self, ip_addr: str) -> None:
        """Enable node"""
        await self.run(
            "UPDATE yascheduler_nodes SET enabled=TRUE WHERE ip=:ip;",
            ip=ip_addr,
        )

    # START_CONTRACT: disable_node
    #   PURPOSE: Disable a node from task scheduling
    #   INPUTS: { ip_addr: str - node IP to disable }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Sets enabled=FALSE on the node
    #   LINKS: [M-DB]
    # END_CONTRACT: disable_node
    async def disable_node(self, ip_addr: str) -> None:
        """Disable node"""
        await self.run(
            "UPDATE yascheduler_nodes SET enabled=FALSE WHERE ip=:ip;",
            ip=ip_addr,
        )

    async def remove_node(self, ip_addr: str) -> None:
        """Remove node"""
        await self.run("DELETE FROM yascheduler_nodes WHERE ip=:ip;", ip=ip_addr)

    # START_CONTRACT: get_task
    #   PURPOSE: Retrieve a single task by its ID
    #   INPUTS: { task_id: int - unique task identifier }
    #   OUTPUTS: { Optional[TaskModel] - task if found, None otherwise }
    #   SIDE_EFFECTS: None
    #   LINKS: [M-DB]
    # END_CONTRACT: get_task
    async def get_task(self, task_id: int) -> Optional[TaskModel]:
        """Get task"""
        rows = await self.run(
            """SELECT task_id, label, ip, status, metadata
                FROM yascheduler_tasks
                WHERE task_id=:task_id;""",
            task_id=task_id,
        )
        for row in rows or []:
            return TaskModel(*row)

    async def get_task_ids_by_ip_and_status(
        self, ip_addr: str, status: TaskStatus
    ) -> Sequence[int]:
        """Get task ids by ip and status"""
        rows = await self.run(
            """SELECT task_id FROM yascheduler_tasks
            WHERE ip=:ip AND status=:status
            ORDER BY task_id;""",
            ip=ip_addr,
            status=status.value,
        )
        return [cast(int, x[0]) for x in (rows or [])]

    async def get_tasks_by_jobs(self, jobs: Sequence[int]) -> Sequence[TaskModel]:
        """Get tasks by ids"""
        rows = await self.run(
            """SELECT task_id, label, ip, status, metadata
            FROM yascheduler_tasks
            WHERE task_id IN (SELECT unnest(CAST (:task_ids AS int[]))) ORDER BY task_id;""",
            task_ids=jobs,
        )
        return [TaskModel(*x) for x in (rows or [])]

    # START_CONTRACT: get_tasks_by_status
    #   PURPOSE: Query tasks filtered by one or more statuses
    #   INPUTS: { statuses: Sequence[TaskStatus] - statuses to filter by, limit: Optional[int] - max results (None for unlimited) }
    #   OUTPUTS: { Sequence[TaskModel] - matching tasks }
    #   SIDE_EFFECTS: None
    #   LINKS: [M-DB]
    # END_CONTRACT: get_tasks_by_status
    async def get_tasks_by_status(
        self, statuses: Sequence[TaskStatus], limit: Optional[int] = None
    ) -> Sequence[TaskModel]:
        """Get tasks by status"""
        rows = await self.run(
            """SELECT task_id, label, ip, status, metadata
            FROM yascheduler_tasks
            WHERE status IN (SELECT unnest(CAST (:statuses AS int[]))) ORDER BY task_id
            LIMIT :lim;""",
            statuses=[x.value for x in statuses],
            lim=limit,
        )
        return [TaskModel(*x) for x in (rows or [])]

    async def get_tasks_with_cloud_by_id_status(
        self, ids: Sequence[int], status: TaskStatus
    ) -> Sequence[TaskModel]:
        """Get tasks with cloud by id and status"""
        rows = await self.run(
            """SELECT t.task_id, t.label, t.ip, t.status, t.metadata, n.cloud
            FROM yascheduler_tasks AS t
            JOIN yascheduler_nodes AS n ON n.ip=t.ip
            WHERE status=:status AND
            task_id IN (SELECT unnest(CAST (:ids AS int[]))) ORDER BY task_id;""",
            ids=ids,
            status=status.value,
        )
        return [TaskModel(*x) for x in (rows or [])]

    async def count_tasks_by_status(self) -> Mapping[TaskStatus, int]:
        """Count tasks by status"""
        rows = await self.run(
            """SELECT status, COUNT(task_id) FROM yascheduler_tasks
            GROUP BY status ORDER BY status;"""
        )
        data = defaultdict(int)
        for row in rows or []:
            data[TaskStatus(row[0])] = row[1]
        return data

    # START_CONTRACT: add_task
    #   PURPOSE: Insert a new task row
    #   INPUTS: { label: Optional[str] - task label, ip_addr: Optional[str] - node IP, status: TaskStatus - initial status (default TO_DO), metadata: Optional[Mapping[str, Any]] - task metadata }
    #   OUTPUTS: { TaskModel - newly created task with generated ID }
    #   SIDE_EFFECTS: Inserts row into yascheduler_tasks
    #   LINKS: [M-DB]
    # END_CONTRACT: add_task
    async def add_task(
        self,
        label: Optional[str] = None,
        ip_addr: Optional[str] = None,
        status: TaskStatus = TaskStatus.TO_DO,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> TaskModel:
        """Add new task"""
        rows = await self.run(
            """INSERT INTO yascheduler_tasks (label, metadata, ip, status)
            VALUES (:label, :metadata, :ip, :status)
            RETURNING task_id, label, ip, status, metadata;""",
            label=label or "",
            metadata=metadata,
            ip=ip_addr,
            status=status.value,
        )
        return TaskModel(*cast(list, rows)[0])

    async def update_task_meta(self, task_id: int, metadata: Mapping[str, Any]):
        """Update task metadata"""
        await self.run(
            "UPDATE yascheduler_tasks SET metadata=:metadata WHERE task_id=:task_id;",
            task_id=task_id,
            metadata=metadata,
        )

    # START_CONTRACT: set_task_running
    #   PURPOSE: Mark task as RUNNING and bind it to a node IP
    #   INPUTS: { task_id: int - task to update, ip_addr: str - node IP the task runs on }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Updates task status to RUNNING and sets IP
    #   LINKS: [M-DB]
    # END_CONTRACT: set_task_running
    async def set_task_running(self, task_id: int, ip_addr: str):
        """Set task running"""
        # START_BLOCK_SET_RUNNING
        await self.run(
            """UPDATE yascheduler_tasks
            SET status=:status, ip=:ip
            WHERE task_id=:task_id;""",
            task_id=task_id,
            status=TaskStatus.RUNNING.value,
            ip=ip_addr,
        )
        # END_BLOCK_SET_RUNNING

    # START_CONTRACT: set_task_done
    #   PURPOSE: Set task status to DONE and update its metadata
    #   INPUTS: { task_id: int - task to mark done, metadata: Mapping[str, Any] - final metadata snapshot }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Updates task status to DONE and sets metadata
    #   LINKS: [M-DB]
    # END_CONTRACT: set_task_done
    async def set_task_done(self, task_id: int, metadata: Mapping[str, Any]):
        """Set task done"""
        # START_BLOCK_SET_DONE
        await self.run(
            """UPDATE yascheduler_tasks
            SET status=:status, metadata=:metadata
            WHERE task_id=:task_id;""",
            task_id=task_id,
            metadata=metadata,
            status=TaskStatus.DONE.value,
        )
        # END_BLOCK_SET_DONE

    # START_CONTRACT: set_task_error
    #   PURPOSE: Mark task as DONE with error metadata (embeds error in metadata if provided)
    #   INPUTS: { task_id: int - task to mark, metadata: Mapping[str, Any] - existing metadata, error: Optional[str] - error message to embed in metadata }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Updates task status to DONE; appends error key to metadata
    #   LINKS: [M-DB]
    # END_CONTRACT: set_task_error
    async def set_task_error(
        self, task_id: int, metadata: Mapping[str, Any], error: Optional[str] = None
    ):
        """Set task error"""
        new_meta = (
            dict(list(metadata.items()) + [("error", error)]) if error else metadata
        )
        await self.run(
            """UPDATE yascheduler_tasks
            SET status=:status, metadata=:metadata
            WHERE task_id=:task_id;""",
            task_id=task_id,
            metadata=new_meta,
            status=TaskStatus.DONE.value,
        )
