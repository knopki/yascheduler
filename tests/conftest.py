# FILE: tests/conftest.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Shared pytest fixtures for the yascheduler test suite.
#   SCOPE: Common fixtures used across unit, integration, and e2e tests.
#   DEPENDS: none
#   LINKS: none
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   anyio_backend - returns "asyncio" for pytest-anyio compatibility
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial test infrastructure: shared fixtures
# END_CHANGE_SUMMARY

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
