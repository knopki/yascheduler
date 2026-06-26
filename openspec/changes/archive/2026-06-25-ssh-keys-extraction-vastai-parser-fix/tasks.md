## 1. SSH keys extraction

- [x] 1.1 Create `yascheduler/infra/ssh/keys.py` with `list_private_keys(keys_dir: Path) -> Sequence[PurePath]`, copying the discovery logic from `ConfigLocal.get_private_keys()` (same directory scan, same file matching). Use `keys_dir.iterdir()` directly — the argument is already a `Path`; tests pass MagicMock `keys_dir` where `Path(keys_dir).iterdir()` would raise `TypeError`.
- [x] 1.2 Add GRACE-lite MODULE_CONTRACT + MODULE_MAP + CHANGE_SUMMARY to `keys.py`; add `M-SSH-KEYS` node under `M-SSH-GATEWAY` in `docs/knowledge-graph.xml`
- [x] 1.3 Update `yascheduler/application/orchestrator.py`: add a `list_private_keys_fn: Callable[[PurePath], Sequence[PurePath]]` parameter to `Orchestrator.__init__`, store it as `self._list_private_keys_fn`, and replace the `self._config.local.get_private_keys` reference at the `_connect_machine_consumer` call site (line ~222) with `self._list_private_keys_fn` (bound callable passed to `run_in_executor`, same shape as the prior bound method). Do NOT import `list_private_keys` from `yascheduler.infra.ssh.keys` in `orchestrator.py` — that would violate the R3 layers contract (application → infra). The orchestrator stays free of any `yascheduler.infra` import.
- [x] 1.4 Update `yascheduler/infra/cloud/manager.py` call site (in `_connect_to_vm`): `self.local_config.get_private_keys()` → `list_private_keys(self.local_config.keys_dir)` (import `list_private_keys` from `yascheduler.infra.ssh.keys` — intra-infra, R3-legal)
- [x] 1.5 Update `yascheduler/entrypoints/cli/manage_node.py` call site: `config.local.get_private_keys()` → `list_private_keys(config.local.keys_dir)` (import from `yascheduler.infra.ssh.keys` — entrypoints → infra, R3-legal)
- [x] 1.6 Update `yascheduler/entrypoints/cli/check_status.py` call site: `config.local.get_private_keys()` → `list_private_keys(config.local.keys_dir)` (import from `yascheduler.infra.ssh.keys` — entrypoints → infra, R3-legal)
- [x] 1.7 Update `yascheduler/entrypoints/di.py` composition root: import `list_private_keys` from `yascheduler.infra.ssh.keys` and pass `list_private_keys_fn=list_private_keys` to the `Orchestrator(...)` constructor call (entrypoints → infra, R3-legal)
- [x] 1.8 Verify zero remaining `get_private_keys` references in `yascheduler/` outside the new `keys.py` (grep check)
- [x] 1.9 Verify `uv run lint-imports` passes — in particular that `application/orchestrator.py` has no runtime import from `yascheduler.infra`

## 2. ConfigLocal attrs→dataclass migration

- [x] 2.1 Rewrite `yascheduler/config/local.py`: replace `@define(frozen=True)` with `@dataclass(frozen=True)`; move attrs `validators.instance_of` / `validators.ge` checks into a `__post_init__` raising `ValueError`; remove `get_private_keys` method; keep `keys_dir: Path` field
- [x] 2.2 Remove the `from attrs import ...` import and `from .utils import make_default_field` (if no longer used) from `local.py`
- [x] 2.3 Update `CHANGE_SUMMARY` in `local.py` with the attrs→dataclass migration note
- [x] 2.4 Update `M-CONFIG-LOCAL` annotation in `docs/knowledge-graph.xml` to drop `get_private_keys`
- [x] 2.5 Run `uv run pytest -m unit -k config` and fix any `ConfigLocal` assertion failures from the dataclass migration (frozen, no method)

## 3. VastAI parser bug fix

- [x] 3.1 In `yascheduler/config/config.py`, add `ConfigCloudVastAI` to the `cloud_variants` tuple (alongside `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`)
- [x] 3.2 Add `from .cloud import ConfigCloudVastAI` import to `config.py` if not already present
- [x] 3.3 Update `CHANGE_SUMMARY` in `config.py` with the VastAI parser fix note

## 4. Tests

- [x] 4.1 Add unit test `test_vastai_cloud_section_round_trips` in `tests/unit/test_config.py`: build a `ConfigParser` with a `[cloud.vastai]` section, call `Config.from_config_parser`, assert `config.clouds` contains a `ConfigCloudVastAI` with `prefix == "vastai"`
- [x] 4.2 Update existing `ConfigLocal` tests in `tests/unit/test_config.py` for the dataclass migration: assert `ConfigLocal` is a stdlib `@dataclass(frozen=True)`, has no `get_private_keys` attribute, retains `keys_dir`
- [x] 4.3 Add unit test for `list_private_keys` in `tests/unit/test_ssh_keys.py` (or `test_config.py` if more appropriate): with a tmp `keys_dir` containing key files, assert the returned paths match
- [x] 4.4 Verify the six test files mocking `config.local.get_private_keys` on MagicMock (`test_cli_check_status.py`, `test_cli_show_nodes.py`, `test_cloud_provisioner_impl.py`, `test_cli_submit.py`, `test_cli_behavioral.py`, `test_cli_manage_node.py`) still pass — they mock `config.local` (duck-typed), not the removed import path. (Also covers 2 `MagicMock(spec=ConfigLocal)` in `test_di.py` / `test_application_orchestrator.py` — confirmed they never access `get_private_keys`; covered by 5.1's full unit run.)

## 5. Verification

- [x] 5.1 Run `uv run pytest -m unit` — all unit tests pass
- [x] 5.2 Run `uv run ruff check .` and `uv run ruff format --check .` — clean
- [x] 5.3 Run `uv run lint-imports` — layers contract passes (no change expected; P1 does not touch layers)
- [x] 5.4 Run `python3 scripts/grace_check.py` — XML + source checks pass
- [x] 5.5 Run `openspec validate --all --json` — spec validation passes
- [x] 5.6 Grep `get_private_keys` in `yascheduler/` — zero matches outside `infra/ssh/keys.py` (which defines `list_private_keys`, not `get_private_keys`)
- [x] 5.7 Grep `attrs` in `yascheduler/config/local.py` — zero matches (attrs fully removed from this file)