## 1. Remove `_*_AVAILABLE` from provider modules and update tests

- [x] 1.1 Remove `_*_AVAILABLE` pattern from `yascheduler/infra/cloud/providers/az.py` — drop `try/except ImportError`, `_AZURE_AVAILABLE`, `if not _AZURE_AVAILABLE` guards, and conditional `RETRY_AZURE_ERRORS`/`ALL_AZURE_ERRORS` (make unconditional)
- [x] 1.2 Remove `_*_AVAILABLE` pattern from `yascheduler/infra/cloud/providers/hetzner.py` — drop `try/except ImportError`, `_HETZNER_AVAILABLE`, and `if not _HETZNER_AVAILABLE` guards
- [x] 1.3 Remove `_*_AVAILABLE` pattern from `yascheduler/infra/cloud/providers/upcloud.py` — drop `try/except ImportError`, `_UPCLOUD_AVAILABLE`, and `if not _UPCLOUD_AVAILABLE` guards
- [x] 1.4 Remove `_*_AVAILABLE` patches and `if not _*_AVAILABLE: raise ImportError` test cases from `tests/unit/test_cloud_provider_create_delete.py`
- [x] 1.5 Verify all unit tests pass after the changes
