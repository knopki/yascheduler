## Why

`ConfigLocal.get_private_keys()` performs filesystem I/O inside a frozen-looking attrs dataclass, mixing a value object with disk access. Separately, `Config.from_config_parser` hardcodes the cloud config variant tuple as `(ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud)` and omits `ConfigCloudVastAI`, so `[cloud.vastai]` INI sections are silently ignored despite the class being re-exported by the `yascheduler.config` facade — a latent bug. This change extracts SSH key loading into a pure function and closes the parser gap as the first, low-risk step of the config-layer split plan (`docs/config-layer-split-plan.md`, P1).

## What Changes

- Extract `ConfigLocal.get_private_keys()` into `infra/ssh/keys.py::list_private_keys(keys_dir) -> Sequence[PurePath]` — a module-level function, no instance state.
- Update the four call sites (`application/orchestrator.py`, `infra/cloud/manager.py`, `entrypoints/cli/manage_node.py`, `entrypoints/cli/check_status.py`) to call `list_private_keys(config.local.keys_dir)` instead of `config.local.get_private_keys()`.
- Add `ConfigCloudVastAI` to the `cloud_variants` tuple in `Config.from_config_parser` so VastAI INI sections round-trip into `Config.clouds`.
- Migrate `ConfigLocal` from attrs to stdlib `@dataclass(frozen=True)`, relocating its field validators into a `__post_init__` (or parser-side validation where the field is set from INI). Drop the `get_private_keys` method; `keys_dir` remains a plain `Path` field.
- Add a focused unit test verifying `Config.from_config_parser` produces a `ConfigCloudVastAI` entry for a `[cloud.vastai]` section (closing the regression gap).

## Capabilities

### New Capabilities
- `ssh-keys-loading`: Pure-function SSH private-key discovery from a keys directory, consumed by the orchestrator, cloud provisioner, and node-management CLI.

### Modified Capabilities
- `testing-unit`: The config-parsing requirement SHALL include a VastAI round-trip assertion (`Config.from_config_parser` produces a `ConfigCloudVastAI` entry for a `[cloud.vastai]` section) alongside the existing Hetzner/UpCloud/Azure parsing coverage. The `ConfigLocal` dataclass migration (frozen, no `get_private_keys` method) is also reflected in the config-parsing test scope.

## Impact

- **Code**: `yascheduler/config/local.py` (attrs→dataclass, method removal), `yascheduler/infra/ssh/keys.py` (new module), `yascheduler/application/orchestrator.py`, `yascheduler/infra/cloud/manager.py`, `yascheduler/entrypoints/cli/manage_node.py`, `yascheduler/entrypoints/cli/check_status.py` (call-site updates), `yascheduler/config/config.py` (one-line tuple extension).
- **APIs**: `ConfigLocal.get_private_keys()` is removed; replaced by `list_private_keys(keys_dir)`. No public API surface (`Yascheduler`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`) is affected. `ConfigLocal` stays importable from `yascheduler.config` for now (the package is removed only in P4).
- **Dependencies**: `attrs` usage in `config/local.py` removed; `attrs` remains a project dependency until P5 (other config and cloud modules still use it).
- **Specs**: New `ssh-keys-loading` capability spec. `openspec/specs/testing-unit/spec.md` config-parsing requirement gains a VastAI round-trip assertion and reflects the `ConfigLocal` dataclass migration.
- **Tests**: New unit test for VastAI parsing; existing `tests/unit/test_config.py::ConfigLocal` assertions updated for the dataclass migration (frozen, no method). Six test files mock `config.local.get_private_keys` on MagicMock objects (`test_cli_check_status.py`, `test_cli_show_nodes.py`, `test_cloud_provisioner_impl.py`, `test_cli_submit.py`, `test_cli_behavioral.py`, `test_cli_manage_node.py`); reviewed and confirmed unaffected — MagicMock accepts arbitrary attribute assignment, and the mocks target `config.local` (the dataclass instance), not the removed method's import path.
- **Knowledge graph**: `M-SSH-KEYS` added under `M-SSH-GATEWAY`; `M-CONFIG-LOCAL` annotation updated to drop `get_private_keys`.