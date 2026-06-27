# FILE: yascheduler/infra/ssh/platform/paths.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Normalize remote data/engines/tasks dirs using the adapter's path type.
#   SCOPE: _init_paths (moved verbatim from helpers.py).
#   DEPENDS: M-PLATFORM-ADAPTERS
#   LINKS: M-PLATFORM-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _init_paths - Normalize remote data/engines/tasks dirs using adapter path type.
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from infra/ssh/helpers.py (decompose-ssh-gateway); _init_paths moved verbatim, no behavioral change.
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import PurePath

    from .adapters import RemoteMachineAdapter


# START_CONTRACT: _init_paths
#   PURPOSE: Normalize remote data/engines/tasks dirs using adapter path type
#   LINKS: none
# END_CONTRACT: _init_paths
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
