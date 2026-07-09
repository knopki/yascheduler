# b131184 — Large commit: add vultr adapter, config, test script

**Date:** 2026-07-03
**Author:** alinzh

The initial Vultr integration: a complete bare-metal cloud adapter for
yascheduler, plus config, documentation, and a standalone test script.

## Files changed (9 files, +810 lines)

### Added

- **`yascheduler/clouds/vultr.py`** (+266) — REST client over `urllib`,
  `VultrClient`, `build_baremetal_user_data` (cloud-init), `vultr_create_node`
  / `vultr_delete_node` (async wrappers), `get_ssh_key_id`, SSH fingerprint
  helper. Initial version used `time.sleep(90)` after SSH port open (later
  replaced by paramiko retry, then asyncssh).
- **`examples/vultr_test.py`** (+358) — standalone CLI script with
  `create`, `list`, `delete`, `test` subcommands. Uses `urllib` directly,
  builds the same cloud-init as the adapter.
- **`CLOUD.md`** (+76, Vultr section) — setup instructions, bare-metal
  setup description, cost control, config example, standalone test script
  section.

### Modified

- **`yascheduler/config/cloud.py`** (+65) — new `ConfigCloudVultr` class
  with fields: `api_key`, `region`, `plan`, `os_id`, `max_nodes`, `username`,
  `priority`, `idle_tolerance`, `jump_username`, `jump_host`. Added to
  `ConfigCloud` union. Other cloud configs updated to know about vultr
  fields in `warn_unknown_fields`.
- **`yascheduler/clouds/adapters.py`** (+13) — `get_vultr_adapter` with
  `op_limit=2`, `create_node_timeout=1200`, `can_debian_bullseye` check.
- **`yascheduler/clouds/cloud_api_manager.py`** (+8/-5) — register
  `"vultr"` in `CLOUD_ADAPTER_GETTERS`, import `get_vultr_adapter`.
- **`yascheduler/config/config.py`** (+9) — add `ConfigCloudVultr` to
  `cloud_variants` tuple, import.
- **`yascheduler/config/__init__.py`** (+9) — export `ConfigCloudVultr`,
  add to `__all__`.
- **`yascheduler/data/yascheduler.conf`** (+11) — commented example with
  all `vultr_*` keys.

## Design notes

- **urllib (stdlib)** for REST API — no new pip dependency.
- **cloud-init** (`user_data`, base64) applies RAID0 NVMe → `/data`,
  `/dev/shm` 200G, ulimit 65536, ScaLAPACK symlink, apt packages.
- **`op_limit=2`** — bare metal provisions slowly; `create_node_timeout=1200`
  (20 min) accommodates long boot.
- **`idle_tolerance=3600`** (1 hour) — bare metal costs $0.993/hr, keeping
  idle machines is expensive.
- **SSH wait** at this point was a naive `time.sleep(90)` after port 22
  opened — this caused `Permission denied` on the first test run (cloud-init
  had not installed keys yet), triggering redundant instance creation.