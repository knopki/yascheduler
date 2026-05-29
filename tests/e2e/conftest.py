# FILE: tests/e2e/conftest.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Auto-mark all collected tests in this directory as "e2e".
#   SCOPE: pytest_collection_modifyitems hook
#   DEPENDS: none
#   LINKS: none
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   pytest_collection_modifyitems - auto-mark tests as "e2e"
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Auto-mark e2e tests via directory-level conftest hook.
# END_CHANGE_SUMMARY


def pytest_collection_modifyitems(items):
    for item in items:
        if "/tests/e2e/" in str(item.path):
            item.add_marker("e2e")
