## 1. D1 — Explicit DTO→Protocol inheritance (runtime import)

- [x] 1.1 In `yascheduler/infra/cloud/cloud_configs.py`, add a runtime import
  `from yascheduler.domain import CloudConfig` at the top of the file (after
  the existing `from yascheduler.shared import Self`). Verify no circular
  import: `domain/ports.py` imports only stdlib `typing`.
- [x] 1.2 Change the 4 DTO class headers to explicitly inherit `CloudConfig`:
  `class ConfigCloudAzure(CloudConfig):`,
  `class ConfigCloudHetzner(CloudConfig):`,
  `class ConfigCloudUpcloud(CloudConfig):`,
  `class ConfigCloudVastAI(CloudConfig):`. Do NOT change
  `AzureImageReference` (it does not declare the 6 Protocol fields and
  SHALL NOT inherit `CloudConfig`).
- [x] 1.3 Update the `MODULE_MAP` in `cloud_configs.py` to note the explicit
  inheritance (e.g., "ConfigCloudAzure - Azure cloud configuration frozen
  dataclass, explicitly inherits CloudConfig Protocol").
- [x] 1.4 Update the `START_CHANGE_SUMMARY` `LAST_CHANGE` entry in
  `cloud_configs.py` to reference this proposal: "v1.1.0 - 4 ConfigCloud* DTOs
  explicitly inherit the domain CloudConfig Protocol via a runtime
  `from yascheduler.domain import CloudConfig` import (resolve-type-bridge-debt);
  removes the writable-vs-frozen mismatch that forced cast bridges in di.py
  and config_parser.py. AzureImageReference unchanged (not a CloudConfig)."
- [x] 1.5 Run `uv run python -c "from yascheduler.infra.cloud.cloud_configs
  import ConfigCloudAzure; from yascheduler.domain import CloudConfig; print
  (isinstance(ConfigCloudAzure(), CloudConfig))"` — confirm `True` and no
  `NameError`/`ImportError`.
- [x] 1.6 Create `tests/unit/test_cloud_config_protocol_inheritance.py` with at
  least these scenarios:
  - `test_all_four_dtos_inherit_cloud_config`: for each of
    `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
    `ConfigCloudVastAI`, assert `CloudConfig in cls.__mro__` (uses `__mro__`
    introspection, NOT `issubclass` which would raise `TypeError` for
    data-Protocols with non-method members per PEP 544).
  - `test_isinstance_returns_true_for_each_dto`: for each DTO instance,
    `isinstance(dto, CloudConfig) is True`.
  - `test_azure_image_reference_does_not_inherit_cloud_config`: assert
    `CloudConfig not in AzureImageReference.__mro__`.
  - `test_no_issubclass_in_production_code`: grep `yascheduler/` for
    `issubclass.*CloudConfig` and assert zero matches (codifies the PEP 544
    ban discipline).
- [x] 1.7 Run `uv run pytest tests/unit/test_cloud_config_protocol_inheritance.py
  -v` — confirm all 4 tests pass.
- [x] 1.8 Run `uv run lint-imports` — confirm the "Clean architecture layers"
  contract reports `KEPT` (the new `infra → domain` runtime edge is
  permitted).
- [x] 1.9 Run `uv run zuban check` — confirm zero new type errors in
  `cloud_configs.py` or any caller (DTOs now satisfy `Sequence[CloudConfig]`
  via inheritance).

## 2. Cast removal in composition root and parser (D1 unlocks the upcasts)

The 4 `di.py` casts split by direction: 2 are **upcasts** (`list[ConfigCloud]
→ Sequence[CloudConfig]`) removed by D1; 2 are **Protocol→Union downcasts**
(`CloudConfig → ConfigCloud`) retained as honest boundary casts with corrected
comments. Only the 3 upcasts (2 in `di.py`, 1 in `config_parser.py`) are
removed.

- [x] 2.1 In `yascheduler/entrypoints/di.py`, remove the
  `cast("Sequence[CloudConfig]", config.clouds)` upcast (line 212) —
  `config.clouds` is already typed `Sequence[CloudConfig]`; the cast is a
  no-op. `config.clouds=config.clouds` typechecks directly.
- [x] 2.2 In `yascheduler/entrypoints/di.py`, remove the
  `cast("Sequence[CloudConfig]", active_clouds)` upcast (line 216) — after
  D1, `list[ConfigCloud]` is assignable to `Sequence[CloudConfig]` via
  covariance + inheritance; the cast is dead weight.
  `active_clouds=active_clouds` typechecks directly.
- [x] 2.3 In `yascheduler/entrypoints/di.py`, KEEP the 2 Protocol→Union
  downcasts `cast("ConfigCloud", cfg)` (line 163) and
  `cast("list[ConfigCloud]", [...])` (lines 190-197) — these are
  downcasts at the entrypoints→infra boundary (`config.clouds:
  Sequence[CloudConfig]` → infra sinks typed `ConfigCloud`); D1 removes
  the upcast direction only. Rewrite their comments to explain the
  downcast direction (replace the inaccurate "Sequence invariance" prose
  with "Protocol→Union downcast: D1 makes the reverse direction typecheck,
  not this one").
- [x] 2.4 In `yascheduler/entrypoints/di.py`, drop the `cast` import from
  `from typing import TYPE_CHECKING, cast` if `cast` is no longer used in
  the file. **Note:** `cast` is still used by the 2 retained downcasts
  (task 2.3), so the import STAYS.
- [x] 2.5 In `yascheduler/entrypoints/config_parser.py`, remove the
  `cast("Sequence[CloudConfig]", clouds)` upcast at line 686.
- [x] 2.6 In `yascheduler/entrypoints/config_parser.py`, remove the
  now-inaccurate comment at lines 683-685 (prose blaming
  "invariance"). Do NOT add a replacement comment.
- [x] 2.7 Update the `START_CHANGE_SUMMARY` `LAST_CHANGE` entries in `di.py`
  and `config_parser.py` to reference this proposal.
- [x] 2.8 Run `rg -n 'cast\("Sequence\[CloudConfig\]"' yascheduler/` —
  confirm zero matches at the resolved upcast sites
  (`di.py:212,216`, `config_parser.py:686`). The 2 retained downcasts
  (`di.py:163` `cast("ConfigCloud"`, `di.py:190` `cast("list[ConfigCloud]"`)
  remain and are documented as honest boundary casts.
- [x] 2.9 Run `uv run zuban check`, `uv run ruff check .`,
  `uv run ruff format --check .` — confirm all clean.
- [x] 2.10 Run `uv run pytest -m unit` — confirm no existing tests broke
  (especially `tests/unit/test_di.py` and `tests/unit/test_cloud_provisioner_impl.py:523`
  which asserts `isinstance(cc, CloudConfig)`).

## 3. D2 — Hoist missing-spawn ValueError

- [x] 3.1 In `yascheduler/entrypoints/config_parser.py`, in
  `parse_engine_section`, add a `None` check on `spawn` BEFORE the
  `Engine(...)` constructor call:
  ```python
  spawn = sec.get("spawn")
  if spawn is None:
      raise ValueError(f"Engine {name} has no spawn command")
  ```
- [x] 3.2 Remove the `# type: ignore[arg-type]` annotation on the
  `spawn=spawn` argument of the `Engine(...)` constructor call (line 175).
  `spawn` is now narrowed to `str` by the hoisted check.
- [x] 3.3 Verify `_check_spawn(engine, engine.spawn)` (called AFTER the
  constructor at line 188) now receives a guaranteed `str`; no defensive
  change needed in `_check_spawn`.
- [x] 3.4 Update the `START_CHANGE_SUMMARY` `LAST_CHANGE` entry in
  `config_parser.py` to note the hoist (the entry added in task 2.8 can be
  amended to include this).
- [x] 3.5 Create `tests/unit/test_parse_engine_spawn_required.py` with at
  least these scenarios:
  - `test_parse_engine_section_raises_value_error_on_missing_spawn`: builds a
    `ConfigParser` with an `[engine.fleur]` section lacking `spawn`, calls
    `parse_engine_section(sec, engines_dir)`, asserts `pytest.raises(ValueError)`
    with a message containing the engine name (`fleur`) and `has no spawn
    command`.
  - `test_parse_engine_section_does_not_raise_when_spawn_present`: builds a
    section with `spawn = echo hi`, asserts no exception and the returned
    `Engine.spawn == "echo hi"`.
- [x] 3.6 Run `uv run pytest tests/unit/test_parse_engine_spawn_required.py
  -v` — confirm both tests pass.
- [x] 3.7 Run `uv run pytest -m unit` — confirm no existing tests broke
  (grep `tests/` for `AttributeError.*spawn\|spawn.*AttributeError` first;
  if any test asserts the old `AttributeError`, update it to assert
  `ValueError`).

## 4. D3a — Retype Azure `_render_custom_data` and add boundary guard

- [x] 4.1 In `yascheduler/infra/cloud/providers/az.py`, change the parameter
  type of `_render_custom_data` from `PCloudConfig | None` to `CloudConfig |
  None` (the concrete `infra/cloud/cloud_config.CloudConfig` class, not the
  domain Protocol). Add the import
  `from yascheduler.infra.cloud.cloud_config import CloudConfig` at the top
  of `az.py` (or use the existing facade `from yascheduler.infra.cloud
  import CloudConfig`).
- [x] 4.2 Change the parameter type of the private `create_node` and
  `create_vm_params` functions from `PCloudConfig | None` to `CloudConfig |
  None` (no external callers; no contravariance risk).
- [x] 4.3 Keep `az_create_node`'s public `cloud_config` parameter at
  `PCloudConfig | None` (preserves assignability to `CreateNodeCallable` at
  `adapters.py:112`).
- [x] 4.4 In `az_create_node`, add a boundary guard before forwarding
  `cloud_config` to `create_node`:
  ```python
  if cloud_config is not None and not isinstance(cloud_config, CloudConfig):
      raise TypeError(
          f"az_create_node expects infra CloudConfig, got "
          f"{type(cloud_config).__name__}"
      )
  ```
- [x] 4.5 Remove the `# type: ignore[misc]` annotation on the
  `.render_base64()` call at `az.py:210` — `replace(cloud_config, bootcmd=...)`
  now returns `CloudConfig`, which has a concrete `render_base64()`.
- [x] 4.6 Update the `START_CHANGE_SUMMARY` `LAST_CHANGE` entry in `az.py`
  to reference this proposal.
- [x] 4.7 Run `uv run zuban check` — confirm zero new errors at `adapters.py:112`
  (the `create_node=az_create_node` assignment) and at `az.py:210` (the
  `render_base64()` call).
- [x] 4.8 Run `uv run ruff check .` and `uv run ruff format --check .` —
  confirm clean.

## 5. D4 — `cast("int", f.default)` in settings

- [x] 5.1 In `yascheduler/domain/settings.py`, change line 112 from
  `f.name: f.default  # type: ignore[dict-item]` to
  `f.name: cast("int", f.default)`.
- [x] 5.2 Add `cast` to the `from typing import ...` import at the top of
  `settings.py` (if `cast` is not already imported).
- [x] 5.3 Update the `START_CHANGE_SUMMARY` `LAST_CHANGE` entry in
  `settings.py` to reference this proposal.
- [x] 5.4 Run `uv run zuban check` — confirm the `# type: ignore[dict-item]`
  is gone and no new error appears.
- [x] 5.5 Run `uv run pytest tests/unit/test_config.py -v` — confirm the
  `_INT_DEFAULTS` derivation tests still pass.

## 6. D5 — `_get_opt_str` helper for TaskContext.from_metadata

- [x] 6.1 In `yascheduler/domain/model.py`, add a module-private helper
  `_get_opt_str(metadata: Mapping[str, object], key: str) -> str | None`:
  ```python
  def _get_opt_str(metadata: Mapping[str, object], key: str) -> str | None:
      value = metadata.get(key)
      if value is None or isinstance(value, str):
          return value
      raise TypeError(
          f"TaskContext JSONB field {key!r} expected str or None, "
          f"got {type(value).__name__}"
      )
  ```
- [x] 6.2 In `TaskContext.from_metadata`, route the 4 `str | None` field
  assignments through `_get_opt_str`:
  - `remote_folder=_get_opt_str(metadata, "remote_folder"),`
  - `local_folder=_get_opt_str(metadata, "local_folder"),`
  - `webhook_url=_get_opt_str(metadata, "webhook_url"),`
  - `error=_get_opt_str(metadata, "error"),`
- [x] 6.3 Drop the `# type: ignore[arg-type]` annotations on those 4
  assignments (lines 155-157, 159).
- [x] 6.4 Drop the `# type: ignore[arg-type]` on the
  `webhook_custom_params=webhook_custom_params,` assignment (line 158) —
  the existing `isinstance(wcp, dict)` guard at lines 151-152 already
  narrows `object` to `dict`, which is assignable to `dict[str, object]`.
- [x] 6.5 Verify the `engine` field still uses `str(metadata.get("engine",
  ""))` (no change; coercion via `str()` is intentional).
- [x] 6.6 Update the `START_CHANGE_SUMMARY` `LAST_CHANGE` entry in
  `domain/model.py` to reference this proposal.
- [x] 6.7 Create `tests/unit/test_task_context_from_metadata_type_safety.py`
  with at least these scenarios:
  - `test_from_metadata_raises_type_error_on_non_str_remote_folder`:
    `from_metadata({"engine": "fleur", "remote_folder": 123})` →
    `pytest.raises(TypeError)`, message mentions `remote_folder` and `int`.
  - `test_from_metadata_raises_type_error_on_non_str_local_folder`: list
    value.
  - `test_from_metadata_raises_type_error_on_non_str_webhook_url`: dict
    value.
  - `test_from_metadata_raises_type_error_on_non_str_error`: float value.
  - `test_from_metadata_accepts_none_for_str_or_none_fields`: explicit
    `None` for `remote_folder` and `error` → no exception, fields are
    `None`.
  - `test_from_metadata_coerces_engine_to_str`: `{"engine": 42}` →
    `TaskContext.engine == "42"`.
  - `test_from_metadata_accepts_dict_for_webhook_custom_params`: dict
    value → preserved.
  - `test_from_metadata_falls_back_to_empty_dict_for_non_dict_webhook_custom_params`:
    `{"engine": "fleur", "webhook_custom_params": "not-a-dict"}` →
    `webhook_custom_params == {}` (existing behavior preserved; NO
    `TypeError` for this field).
- [x] 6.8 Run `uv run pytest tests/unit/test_task_context_from_metadata_type_safety.py
  -v` — confirm all 8 tests pass.
- [x] 6.9 Run `uv run pytest -m unit` — confirm no existing tests broke
  (especially `tests/unit/test_domain_model.py` and
  `tests/unit/test_persistence_adapter.py` which exercise `from_metadata`).

## 7. D6 — Comment and docstring corrections

- [x] 7.1 In `yascheduler/domain/ports.py`, update the `CloudConfig`
  Protocol docstring (currently lines 101-108) to remove the phrase
  "(no explicit inheritance)" and state: "Satisfied by every `ConfigCloud*`
  DTO in `infra/cloud/cloud_configs.py` — the DTOs inherit this Protocol
  explicitly (typing aid); a DTO outside the inheritance tree still
  satisfies it structurally (PEP 544)."
- [x] 7.2 In `openspec/specs/domain-ports/spec.md`, remove the CloudConfig
  sub-prose under the `### Requirement: MachineGateway port` block (the
  paragraph at lines 100-117 beginning "The system SHALL define a
  `CloudConfig` structural Protocol with attributes ..."). The CloudConfig
  contract now stands as its own requirement per the `domain-ports` delta
  spec. Verify by running:
  ```bash
  sed -n '/^### Requirement: MachineGateway port$/,/^### /p' openspec/specs/domain-ports/spec.md | rg -c 'CloudConfig' && echo "STILL PRESENT" || echo "REMOVED"
  ```
  Expect `REMOVED`. (Note: this task edits the **spec file** at
  `openspec/specs/domain-ports/spec.md`, not the code file at
  `yascheduler/domain/ports.py` — the spec carries the prose; the code carries
  the Protocol class definition and its docstring.)
- [x] 7.3 In `openspec/specs/domain-ports/spec.md`, remove the
  `CloudConfig is runtime_checkable and satisfied by ConfigCloud DTOs`
  Scenario previously at the end of the `MachineGateway port` Requirement
  (lines 162-164). It is now covered by the standalone
  `CloudConfig structural Protocol` Requirement per the `domain-ports` delta.
  Verify by running:
  ```bash
  sed -n '/^### Requirement: MachineGateway port$/,/^### /p' openspec/specs/domain-ports/spec.md | rg -c 'runtime_checkable and satisfied'
  ```
  Expect `0`.
- [x] 7.4 Update the `START_CHANGE_SUMMARY` `LAST_CHANGE` entry in
  `domain/ports.py` to reference this proposal.

## 8. D7 — Knowledge graph and final CHANGE_SUMMARY sweep

- [x] 8.1 In `docs/knowledge-graph.xml`, add `M-DOMAIN-PORTS` to the
  `<depends>` of `M-CLOUD-CONFIGS` (the DTOs now explicitly reference the
  domain Protocol via a runtime import).
- [x] 8.2 In `docs/knowledge-graph.xml`, add a new `<CrossLink
  from="M-CLOUD-CONFIGS" to="M-DOMAIN-PORTS" relation="DTOs explicitly
  inherit CloudConfig Protocol as typing aid (structural matching still
  works without inheritance)" />`.
- [x] 8.3 Verify the 7 `START_CHANGE_SUMMARY` `LAST_CHANGE` entries are
  refreshed in the touched modules:
  - `infra/cloud/cloud_configs.py` (task 1.4)
  - `domain/ports.py` (task 7.4)
  - `entrypoints/di.py` (task 2.8)
  - `entrypoints/config_parser.py` (task 2.8 + 3.4)
  - `infra/cloud/providers/az.py` (task 4.6)
  - `domain/settings.py` (task 5.3)
  - `domain/model.py` (task 6.6)
- [x] 8.4 Run `python3 scripts/grace_check.py` — confirm XML and source
  checks pass (the new `CrossLink` is valid; the refreshed `CHANGE_SUMMARY`
  entries are present).

## 9. Spec validation and final verification

- [x] 9.1 Run `openspec validate --all --json` — confirm `valid: true` for
  the change and no broken deltas.
- [x] 9.2 Run `uv run pytest -m unit` — confirm the full unit suite passes
  including the 3 new test files
  (`tests/unit/test_cloud_config_protocol_inheritance.py` created in task 1.6,
  `tests/unit/test_parse_engine_spawn_required.py` created in task 3.5,
  `tests/unit/test_task_context_from_metadata_type_safety.py` created in
  task 6.7).
- [x] 9.3 Run `uv run zuban check` — confirm zero type errors across the
  touched modules.
- [x] 9.4 Run `uv run ruff check .` and `uv run ruff format --check .` —
  confirm clean.
- [x] 9.5 Run `uv run lint-imports` — confirm the "Clean architecture
  layers" contract reports `KEPT`.
- [x] 9.6 Run the final debt-presence grep:
  ```bash
  rg -n 'cast\("Sequence\[CloudConfig\]"|type: ignore\[(arg-type|misc|dict-item)\]' yascheduler/
  ```
  Confirm zero matches at the resolved upcast/ignore sites
  (`di.py:212,216`, `config_parser.py:175,686`, `az.py:210`,
  `settings.py:112`, `model.py:155-159`). The 2 retained Protocol→Union
  downcasts (`di.py:163` `cast("ConfigCloud"`, `di.py:190`
  `cast("list[ConfigCloud]"`) remain and are documented as honest boundary
  casts — they are NOT in the grep pattern (which targets the removable
  `Sequence[CloudConfig]` upcast + the 7 `type: ignore` sites). The
  test-file `# type: ignore` annotations documenting intentional
  frozen-dataclass mutation (e.g., `test_config.py:431,433,560`) stay —
  they are out of scope.
- [x] 9.7 Run `openspec validate resolve-type-bridge-debt --json` — confirm
  `valid: true` and no issues.
- [x] 9.8 Run `python3 scripts/grace_check.py` — confirm exit 0.