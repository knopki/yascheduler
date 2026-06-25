## 1. Migrate leaf cloud dataclasses (no internal cloud deps)

- [x] 1.1 `yascheduler/infra/cloud/protocols.py` — migrate `CloudCapacity` from `attrs.define(frozen=True)` to `dataclasses.dataclass(frozen=True)`; remove the `from attr import define` typo import (line 35); add `from dataclasses import dataclass` import; bump VERSION 1.0.1 → 1.1.0; add CHANGE_SUMMARY entry; verify 3 fields (`name`, `max`, `current`) remain bare annotations
- [x] 1.2 `yascheduler/infra/cloud/cloud_config.py` — migrate `CloudConfig` from `attrs.define(frozen=True)` to `dataclasses.dataclass(frozen=True)`; switch `from attrs import asdict, define, field` → `from dataclasses import asdict, dataclass, field`; map `field(factory=tuple)` → `field(default_factory=tuple)`, `field(factory=list)` → `field(default_factory=list)`, `field(default=False)` unchanged; `render()` now calls `dataclasses.asdict(self)`; bump VERSION 1.0.1 → 1.1.0; add CHANGE_SUMMARY entry; update MODULE_MAP line 12 "Frozen attrs class" → "Frozen dataclass"
- [x] 1.3 `yascheduler/infra/cloud/adapters.py` — migrate `CloudAdapter` from `attrs.define(frozen=True)` to `dataclasses.dataclass(frozen=True)`; switch `from attrs import define, field` → `from dataclasses import dataclass, field`; map 4× bare `field()` → bare annotations (`name`, `supported_platform_checks`, `create_node`, `delete_node`); 3× `field(default=X)` unchanged; remove the `# FIXME: migrate from attrs to dataclasses` marker at line 28; bump VERSION 1.1.1 → 1.2.0; add CHANGE_SUMMARY entry; update MODULE_MAP line 11 "Frozen attrs class" → "Frozen dataclass"

## 2. Migrate the manager (depends on migrated leaf classes)

- [x] 2.1 `yascheduler/infra/cloud/manager.py` — migrate `CloudProvisionerImpl` from `attrs.define(frozen=True)` to `dataclasses.dataclass(frozen=True)`; switch `from attrs import define, field` → `from dataclasses import dataclass, field`; map 7× bare `field()` → bare annotations (`adapters`, `configs`, `machine_gateway`, `local_config`, `remote_config`, `engines`, `log`); map `ssh_key_lock: asyncio.Lock = field(factory=asyncio.Lock, init=False)` → `field(default_factory=asyncio.Lock, init=False)`; bump VERSION 2.1.0 → 2.2.0; add CHANGE_SUMMARY entry

## 3. Make az.py hybrid (depends on migrated CloudConfig)

- [x] 3.1 `yascheduler/infra/cloud/providers/az.py` — split the attrs import: `from attrs import asdict, evolve` → `from attrs import asdict` (keep, needed for `AzureImageReference`) + add `from dataclasses import replace`; change `evolve(cloud_config, bootcmd=[*my_boot_cmds, *cloud_config.bootcmd])` (line 205) → `replace(cloud_config, bootcmd=[*my_boot_cmds, *cloud_config.bootcmd])  # type: ignore[misc]` (zuban fires on `PCloudConfig` Protocol not satisfying `_DataclassT` bound — the ignore is the minimal localized fix); leave `asdict(vm_image)` at line 231 unchanged with its existing `# type: ignore[arg-type]`; bump VERSION 1.6.1 → 1.7.0; add CHANGE_SUMMARY entry

## 4. Update the cloud subpackage facade

- [x] 4.1 `yascheduler/infra/cloud/__init__.py` — bump VERSION 1.5.1 → 1.6.0; add CHANGE_SUMMARY entry; update MODULE_MAP line 12 "Frozen attrs class" → "Frozen dataclass" (no import changes, `__all__` unchanged)

## 5. Add the canary test

- [x] 5.1 `tests/unit/test_cloud_provisioner_impl.py` — add `test_cloud_config_render_serializes` to the existing `TestCloudConfigGeneration` class: construct `CloudConfig(bootcmd=("echo hi", ["mkdir", "/x"]), package_upgrade=True, packages=["vim", "htop"])`, call `render()`, assert startswith `"#cloud-config\n"`, `json.loads` the payload after prefix, assert `payload["bootcmd"] == ["echo hi", ["mkdir", "/x"]]`, `payload["packages"] == ["vim", "htop"]`, `payload["package_upgrade"] is True`; add `import json` to the test file if not already present

## 6. Finalize the spec delta

- [x] 6.1 Verify and finalize `openspec/changes/migrate-cloud-from-attrs/specs/cloud-providers/spec.md` — confirm the MODIFIED delta on "Support modules relocated" is correct: full requirement block copied from `openspec/specs/cloud-providers/spec.md`, import path fixed (`adapters.cloud.adapters` → `yascheduler.infra.cloud.adapters`, THEN clause augmented with "backed by stdlib dataclasses"), new scenario "CloudConfig render output stable across migration" added (WHEN render() called on frozen dataclass / THEN "#cloud-config\n"-prefixed JSON / AND byte-identical to prior attrs-backed implementation), exactly 4 hashtags for scenarios; "Provider code relocated" and "Optional provider SDKs handled gracefully" untouched

## 7. Static checks and validation

- [x] 7.1 Run `uv run zuban check` — must be green; the one NEW `# type: ignore[misc]` on az.py `replace()` call is expected and documented; try removing `# type: ignore[arg-type]` from `cloud_config.py:41` first, restore only if zuban fails
- [x] 7.2 Run `uv run ruff check .` — must be green
- [x] 7.3 Run `uv run ruff format --check .` — must be green (run `uv run ruff format .` if not)
- [x] 7.4 Run `uv run lint-imports` — must be green; verifies `from attrs import` is GONE from the 4 fully-migrated files (`protocols.py`, `cloud_config.py`, `adapters.py`, `manager.py`) and STILL PRESENT in `az.py` as `from attrs import asdict`
- [x] 7.5 Run `uv run pytest -m unit` — must be green; new canary `test_cloud_config_render_serializes` passes; existing `test_cloud_provisioner_impl.py` and `test_provider_selection.py` unaffected (constructor signatures, `MagicMock(spec=CloudAdapter)`, Py 3.9 asyncio.Lock workaround all unchanged)
- [x] 7.6 Run `python3 scripts/grace_check.py` — must exit 0 (XML + source checks: markup valid, file sizes within 500 soft / 1000 hard limits)
- [x] 7.7 Run `openspec validate --all --json` — must pass (spec delta valid against main spec)

## 8. Non-goals verification (defense-in-depth, matches SSH precedent)

- [x] 8.1 Confirm `pyproject.toml` is NOT modified — `attrs>=22.2.0` remains in `[project.dependencies]` (still needed by `yascheduler/config/*` and `az.py`)
- [x] 8.2 Confirm no files outside `yascheduler/infra/cloud/`, `tests/unit/test_cloud_provisioner_impl.py`, and `openspec/changes/migrate-cloud-from-attrs/` were touched