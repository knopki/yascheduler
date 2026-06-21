# FILE: tests/unit/test_application_no_adapter_imports.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Import hygiene: application layer must not import adapter runtime types at module level.
#   SCOPE: Verifies APPLICATION_MODULES do not expose AllSSHRetryExc, SFTPRetryExc, SFTPError, backoff.
#     Allowed: TYPE_CHECKING imports of CloudProvisionerImpl and SSHMachineGateway (orchestrator only).
#   DEPENDS: M-APPLICATION-*
#   LINKS: M-APPLICATION-* modules
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_no_forbidden_adapter_runtime_imports - Parametric: each application module checked for 4 forbidden names
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Import hygiene test for adapter->application boundary (gateway-port-cleanup).
# END_CHANGE_SUMMARY

"""Import hygiene: application layer must not import adapter runtime types.

Allowed: TYPE_CHECKING imports.
Forbidden at runtime: AllSSHRetryExc, SFTPRetryExc, SFTPError, backoff.
"""

import importlib

import pytest

FORBIDDEN_NAMES = {"AllSSHRetryExc", "SFTPRetryExc", "SFTPError", "backoff"}

APPLICATION_MODULES = [
    "yascheduler.application.consume_task",
    "yascheduler.application.allocate_task",
    "yascheduler.application.deallocate_nodes",
    "yascheduler.application.orchestrator",
    "yascheduler.application.submit_task",
]


# START_CONTRACT: test_no_forbidden_adapter_runtime_imports
#   PURPOSE: Verify each application module does not expose any of the 4 forbidden adapter runtime names.
#   INPUTS: { module_name: str - Application module to check }
#   OUTPUTS: { None - raises AssertionError if a forbidden name is found }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_no_forbidden_adapter_runtime_imports
@pytest.mark.parametrize("module_name", APPLICATION_MODULES)
def test_no_forbidden_adapter_runtime_imports(module_name: str) -> None:
    module = importlib.import_module(module_name)
    for name in FORBIDDEN_NAMES:
        assert not hasattr(module, name), (
            f"{module_name} imports forbidden adapter runtime symbol '{name}'"
        )
