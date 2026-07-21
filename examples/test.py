from typing import Literal, Protocol, TypeGuard, reveal_type

from yascheduler.domain import Task, TaskId, TaskStatus


class TodoTask(Protocol):
    status: Literal[TaskStatus.TO_DO]


class RunningTask(Protocol):
    status: Literal[TaskStatus.RUNNING]
    allocated_node_id: int


def test_todo_task(task: Task) -> TypeGuard[TodoTask]:
    return task.status == TaskStatus.TO_DO


def test_running_task(task: Task) -> TypeGuard[RunningTask]:
    return (
        task.status == TaskStatus.RUNNING
        and task.allocated_node_id is not None
        and task.remote_folder is not None
    )


task = Task(task_id=TaskId(1), engine="test")

if test_todo_task(task):
    kek = task.status
    reveal_type(task)

if test_running_task(task):
    reveal_type(task)
    test = task.allocated_node_id
