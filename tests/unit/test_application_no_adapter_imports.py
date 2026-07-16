"""Import hygiene: application layer must not import adapter runtime types.

Allowed: TYPE_CHECKING imports.
Forbidden at runtime: AllSSHRetryExc, SFTPRetryExc, SFTPError, backoff.
"""
# region MODULE_CONTRACT
# PURPOSE: Import hygiene: application layer must not import adapter runtime types at module level.
# SCOPE: Verifies APPLICATION_MODULES do not expose AllSSHRetryExc, SFTPRetryExc, SFTPError, backoff. Allowed: TYPE_CHECKING imports of CloudProvisionerImpl and SSHMachineGateway (orchestrator only).
# KEYWORDS: import hygiene, adapter runtime, TYPE_CHECKING
# endregion MODULE_CONTRACT

import importlib

import pytest

FORBIDDEN_NAMES = {"AllSSHRetryExc", "SFTPRetryExc", "SFTPError", "backoff"}

APPLICATION_MODULES = [
    "yascheduler.application.abandon_node",
    "yascheduler.application.consume_task",
    "yascheduler.application.allocate_task",
    "yascheduler.application.deallocate_nodes",
    "yascheduler.application.orchestrator",
    "yascheduler.application.submit_task",
]


@pytest.mark.parametrize("module_name", APPLICATION_MODULES)
def test_no_forbidden_adapter_runtime_imports(module_name: str) -> None:
    module = importlib.import_module(module_name)
    for name in FORBIDDEN_NAMES:
        assert not hasattr(module, name), (
            f"{module_name} imports forbidden adapter runtime symbol '{name}'"
        )
