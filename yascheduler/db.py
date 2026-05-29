# FILE: yascheduler/db.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: PostgreSQL persistence for tasks, nodes, and their statuses.
#   SCOPE: Task and node CRUD, status transitions, schema migration.
#   DEPENDS: M-CONFIG-DB, M-COMPAT, M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL
#   LINKS: M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL, M-SCHEDULER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   DB: Database abstraction class with async methods for task/node CRUD and status transitions.
#   TaskModel: Immutable task data model (task_id, label, ip, status, metadata, cloud).
#   NodeModel: Immutable node data model (ip, ncpus, enabled, cloud, username, port).
#   TaskStatus: IntEnum of possible task states (TO_DO, RUNNING, DONE).
#   DB._task_repo: PostgresTaskRepository field (initialized in __attrs_post_init__).
#   DB._node_repo: PostgresNodeRepository field (initialized in __attrs_post_init__).
#   DB._task_to_model: Convert domain Task to DB TaskModel.
#   DB._model_to_task: Convert DB TaskModel to domain Task.
#   DB._node_to_model: Convert domain Node to DB NodeModel.
#   DB._model_to_node: Convert DB NodeModel to domain Node.
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Delegate to PostgresTaskRepository/PostgresNodeRepository.
#   PREVIOUS_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

"""Database utils"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum, unique
from typing import Any, Optional

import backoff
from attrs import asdict, define, field
from pg8000.native import Connection, InterfaceError

from .adapters.persistence.postgres import (
    PostgresNodeRepository,
    PostgresTaskRepository,
)
from .compat import Self
from .config import ConfigDb
from .domain.model import (
    Node,
    Task,
)
from .domain.model import (
    TaskContext as DomainTaskContext,
)
from .domain.model import (
    TaskStatus as DomainTaskStatus,
)


@unique
class TaskStatus(IntEnum):
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
    _task_repo: PostgresTaskRepository = field(init=False)
    _node_repo: PostgresNodeRepository = field(init=False)

    def __attrs_post_init__(self) -> None:
        """Initialize repository wrappers after attrs init."""
        object.__setattr__(
            self, "_task_repo", PostgresTaskRepository(self.conn, self.executor)
        )
        object.__setattr__(
            self, "_node_repo", PostgresNodeRepository(self.conn, self.executor)
        )

    # START_CONTRACT: _task_to_model
    #   PURPOSE: Convert domain Task to DB TaskModel.
    #   INPUTS: { task: Task - domain task }
    #   OUTPUTS: { TaskModel }
    #   SIDE_EFFECTS: None
    #   LINKS: Task, TaskModel, TaskContext
    # END_CONTRACT: _task_to_model
    def _task_to_model(self, task: Task) -> TaskModel:
        """Convert domain Task to DB TaskModel."""
        return TaskModel(
            task_id=task.task_id,
            label=task.label,
            ip=task.allocated_ip or "",
            status=TaskStatus(task.status.value),
            metadata={**task.context.to_metadata()},
        )

    # START_CONTRACT: _model_to_task
    #   PURPOSE: Convert DB TaskModel to domain Task.
    #   INPUTS: { model: TaskModel - DB task model }
    #   OUTPUTS: { Task }
    #   SIDE_EFFECTS: None
    #   LINKS: TaskModel, Task, TaskContext
    # END_CONTRACT: _model_to_task
    def _model_to_task(self, model: TaskModel) -> Task:
        """Convert DB TaskModel to domain Task."""
        ctx = DomainTaskContext.from_metadata(dict(model.metadata))
        return Task(
            task_id=model.task_id,
            label=model.label,
            context=ctx,
            status=DomainTaskStatus(model.status.value),
            allocated_ip=model.ip or None,
        )

    # START_CONTRACT: _node_to_model
    #   PURPOSE: Convert domain Node to DB NodeModel.
    #   INPUTS: { node: Node - domain node }
    #   OUTPUTS: { NodeModel }
    #   SIDE_EFFECTS: None
    #   LINKS: Node, NodeModel
    # END_CONTRACT: _node_to_model
    def _node_to_model(self, node: Node) -> NodeModel:
        """Convert domain Node to DB NodeModel."""
        return NodeModel(
            ip=node.ip,
            ncpus=node.ncpus or None,
            enabled=node.enabled,
            cloud=node.cloud,
            username=node.username,
            port=node.port,
        )

    # START_CONTRACT: _model_to_node
    #   PURPOSE: Convert DB NodeModel to domain Node.
    #   INPUTS: { model: NodeModel - DB node model }
    #   OUTPUTS: { Node }
    #   SIDE_EFFECTS: None
    #   LINKS: NodeModel, Node
    # END_CONTRACT: _model_to_node
    def _model_to_node(self, model: NodeModel) -> Node:
        """Convert DB NodeModel to domain Node."""
        return Node(
            ip=model.ip,
            ncpus=model.ncpus or 0,
            enabled=model.enabled,
            cloud=model.cloud,
            username=model.username,
            port=model.port,
        )

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
        node = await self._node_repo.get(ip_addr)
        return bool(node)

    async def update_task_status(self, task_id: int, status: TaskStatus) -> None:
        """Update task status"""
        await self._task_repo.update_status(task_id, DomainTaskStatus(status.value))

    async def get_all_nodes(self) -> Sequence[NodeModel]:
        """Get all nodes"""
        nodes = await self._node_repo.list_all()
        return [self._node_to_model(n) for n in nodes]

    async def get_enabled_nodes(self) -> Sequence[NodeModel]:
        """Get all enabled nodes"""
        nodes = await self._node_repo.list_enabled()
        return [self._node_to_model(n) for n in nodes]

    async def get_disabled_nodes(self) -> Sequence[NodeModel]:
        """Get all disabled nodes"""
        nodes = await self._node_repo.list_disabled()
        return [self._node_to_model(n) for n in nodes]

    async def get_node(self, ip_addr: str) -> Optional[NodeModel]:
        """Get node by ip"""
        node = await self._node_repo.get(ip_addr)
        if node is None:
            return None
        return self._node_to_model(node)

    async def count_nodes_clouds(self) -> Mapping[str, int]:
        """Count nodes in clouds"""
        return await self._node_repo.count_by_cloud()

    async def count_nodes_by_status(self) -> Mapping[bool, int]:
        """Count nodes by status"""
        return await self._node_repo.count_by_status()

    # START_CONTRACT: add_tmp_node
    #   PURPOSE: Add a temporary cloud-provisioned node with generated provisional IP
    #   INPUTS: { cloud: str - cloud provider name, username: str - SSH username for node }
    #   OUTPUTS: { str - generated provisional IP address }
    #   SIDE_EFFECTS: Inserts disabled node with provisional IP into yascheduler_nodes
    #   LINKS: [M-DB]
    # END_CONTRACT: add_tmp_node
    async def add_tmp_node(self, cloud: str, username: str) -> str:
        """Add temporary node"""
        return await self._node_repo.add_tmp(cloud, username=username)

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
        port_val = port or 22
        node = Node(
            ip=ip_addr,
            ncpus=ncpus or 0,
            enabled=enabled,
            cloud=cloud,
            username=username,
            port=port_val,
        )
        await self._node_repo.add(node)
        return self._node_to_model(node)

    # START_CONTRACT: enable_node
    #   PURPOSE: Enable a node for task scheduling
    #   INPUTS: { ip_addr: str - node IP to enable }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Sets enabled=TRUE on the node
    #   LINKS: [M-DB]
    # END_CONTRACT: enable_node
    async def enable_node(self, ip_addr: str) -> None:
        """Enable node"""
        await self._node_repo.enable(ip_addr)

    # START_CONTRACT: disable_node
    #   PURPOSE: Disable a node from task scheduling
    #   INPUTS: { ip_addr: str - node IP to disable }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Sets enabled=FALSE on the node
    #   LINKS: [M-DB]
    # END_CONTRACT: disable_node
    async def disable_node(self, ip_addr: str) -> None:
        """Disable node"""
        await self._node_repo.disable(ip_addr)

    async def remove_node(self, ip_addr: str) -> None:
        """Remove node"""
        await self._node_repo.remove(ip_addr)

    # START_CONTRACT: get_task
    #   PURPOSE: Retrieve a single task by its ID
    #   INPUTS: { task_id: int - unique task identifier }
    #   OUTPUTS: { Optional[TaskModel] - task if found, None otherwise }
    #   SIDE_EFFECTS: None
    #   LINKS: [M-DB]
    # END_CONTRACT: get_task
    async def get_task(self, task_id: int) -> Optional[TaskModel]:
        """Get task"""
        task = await self._task_repo.get(task_id)
        if task is None:
            return None
        return self._task_to_model(task)

    async def get_task_ids_by_ip_and_status(
        self, ip_addr: str, status: TaskStatus
    ) -> Sequence[int]:
        """Get task ids by ip and status"""
        return await self._task_repo.list_ids_by_ip_and_status(
            ip_addr, DomainTaskStatus(status.value)
        )

    async def get_tasks_by_jobs(self, jobs: Sequence[int]) -> Sequence[TaskModel]:
        """Get tasks by ids"""
        tasks = await self._task_repo.list_by_jobs(list(jobs))
        return [self._task_to_model(t) for t in tasks]

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
        status_set = set(DomainTaskStatus(s.value) for s in statuses)
        tasks = await self._task_repo.list_by_status(status_set, limit=limit)
        return [self._task_to_model(t) for t in tasks]

    async def get_tasks_with_cloud_by_id_status(
        self, ids: Sequence[int], status: TaskStatus
    ) -> Sequence[TaskModel]:
        """Get tasks with cloud by id and status"""
        tasks = await self._task_repo.list_by_jobs(list(ids))
        domain_status = DomainTaskStatus(status.value)
        matching = [t for t in tasks if t.status == domain_status]

        ips = [t.allocated_ip for t in matching if t.allocated_ip]
        nodes_by_ip = await self._node_repo.get_by_ips(ips) if ips else {}

        result: list[TaskModel] = []
        for t in matching:
            cloud: Optional[str] = None
            if t.allocated_ip:
                node = nodes_by_ip.get(t.allocated_ip)
                if node is not None:
                    cloud = node.cloud
            model = self._task_to_model(t)
            result.append(
                TaskModel(
                    task_id=model.task_id,
                    label=model.label,
                    ip=model.ip,
                    status=model.status,
                    metadata=model.metadata,
                    cloud=cloud,
                )
            )
        return result

    async def count_tasks_by_status(self) -> Mapping[TaskStatus, int]:
        """Count tasks by status"""
        raw = await self._task_repo.count_by_status()
        return {TaskStatus(k.value): int(v) for k, v in raw.items()}

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
        ctx = DomainTaskContext.from_metadata(dict(metadata or {}))
        domain_task = Task(
            task_id=0,
            label=label or "",
            context=ctx,
            status=DomainTaskStatus(status.value),
            allocated_ip=ip_addr,
        )
        inserted = await self._task_repo.insert(domain_task)
        return self._task_to_model(inserted)

    async def update_task_meta(self, task_id: int, metadata: Mapping[str, Any]):
        """Update task metadata"""
        task = await self._task_repo.get(task_id)
        if task is not None:
            new_ctx = DomainTaskContext.from_metadata(dict(metadata))
            updated = Task(
                task_id=task.task_id,
                label=task.label,
                context=new_ctx,
                status=task.status,
                allocated_ip=task.allocated_ip,
            )
            await self._task_repo.save(updated)

    # START_CONTRACT: set_task_running
    #   PURPOSE: Mark task as RUNNING and bind it to a node IP
    #   INPUTS: { task_id: int - task to update, ip_addr: str - node IP the task runs on }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Updates task status to RUNNING and sets IP
    #   LINKS: [M-DB]
    # END_CONTRACT: set_task_running
    async def set_task_running(self, task_id: int, ip_addr: str):
        """Set task running"""
        task = await self._task_repo.get(task_id)
        if task is not None:
            await self._task_repo.save(task.allocate_to(ip_addr).mark_running())

    # START_CONTRACT: set_task_done
    #   PURPOSE: Set task status to DONE and update its metadata
    #   INPUTS: { task_id: int - task to mark done, metadata: Mapping[str, Any] - final metadata snapshot }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Updates task status to DONE and sets metadata
    #   LINKS: [M-DB]
    # END_CONTRACT: set_task_done
    async def set_task_done(self, task_id: int, metadata: Mapping[str, Any]):
        """Set task done"""
        task = await self._task_repo.get(task_id)
        if task is not None:
            meta = task.context.to_metadata()
            meta.update(metadata)
            updated = Task(
                task_id=task.task_id,
                label=task.label,
                context=DomainTaskContext.from_metadata(meta),
                status=DomainTaskStatus.DONE,
                allocated_ip=task.allocated_ip,
            )
            await self._task_repo.save(updated)

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
        task = await self._task_repo.get(task_id)
        if task is not None:
            new_meta = task.context.to_metadata()
            new_meta.update(metadata)
            if error:
                new_meta["error"] = error
            updated = Task(
                task_id=task.task_id,
                label=task.label,
                context=DomainTaskContext.from_metadata(new_meta),
                status=DomainTaskStatus.DONE,
                allocated_ip=task.allocated_ip,
            )
            await self._task_repo.save(updated)
