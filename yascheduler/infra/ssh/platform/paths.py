"""Normalize remote data/engines/tasks dirs using the adapter's path type."""
# region MODULE_CONTRACT
# PURPOSE: Normalize remote data/engines/tasks dirs using the adapter's path type.
# SCOPE: _init_paths — ensures directory paths match the remote path semantics.
# KEYWORDS: paths, directories, data, engines, tasks, remote
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import PurePath

    from .adapters import RemoteMachineAdapter

__all__ = ["_init_paths"]


# region FUNC__init_paths
# PURPOSE: Normalize remote data/engines/tasks dirs using adapter path type.
def _init_paths(
    adapter: RemoteMachineAdapter,
    data_dir: PurePath | None,
    engines_dir: PurePath | None,
    tasks_dir: PurePath | None,
) -> tuple[PurePath, PurePath, PurePath]:
    path_cls = adapter.path
    if not isinstance(data_dir, path_cls):
        data_dir = path_cls(str(data_dir)) if data_dir else path_cls("./data")
    if not isinstance(engines_dir, path_cls):
        engines_dir = (
            path_cls(str(engines_dir)) if engines_dir else data_dir / "engines"
        )
    if not isinstance(tasks_dir, path_cls):
        tasks_dir = path_cls(str(tasks_dir)) if tasks_dir else data_dir / "tasks"
    return data_dir, engines_dir, tasks_dir


# endregion FUNC__init_paths
