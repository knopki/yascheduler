## Context

`yascheduler/config/local.py` defines `ConfigLocal` as an attrs `@define(frozen=True)` dataclass carrying daemon concurrency limits, directory paths, and a `webhook_url`. It also carries `get_private_keys()`, a method that performs filesystem I/O (scans `keys_dir` for SSH private-key files). This mixes a value object with disk access. Four production call sites invoke it: `application/orchestrator.py`, `infra/cloud/manager.py`, `entrypoints/cli/manage_node.py`, and `entrypoints/cli/check_status.py`.

Separately, `yascheduler/config/config.py::Config.from_config_parser` builds the cloud config list by matching INI section prefixes against a hardcoded tuple `cloud_variants = (ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud)`. `ConfigCloudVastAI` is re-exported by `yascheduler.config.__init__` but is not in that tuple, so `[cloud.vastai]` sections are silently dropped.

The project is migrating off attrs to stdlib dataclasses (already done for `queue.py::UMessage`, `ssh/platform/common.py::ProcessInfo`, `ssh/platform/adapters.py::RemoteMachineAdapter`). `ConfigLocal` is the next attrs class being touched, so it migrates in this change.

This change is P1 of the umbrella plan at `docs/config-layer-split-plan.md`. It deliberately avoids layers-contract changes, package relocations, and any move of `ConfigLocal` out of `yascheduler.config` — those are P2–P4.

## Goals / Non-Goals

**Goals:**
- Remove filesystem I/O from the `ConfigLocal` value object by extracting a pure function `list_private_keys(keys_dir)` into `infra/ssh/keys.py`.
- Update all four call sites to use the function.
- Fix the VastAI parser bug by adding `ConfigCloudVastAI` to the `cloud_variants` tuple.
- Migrate `ConfigLocal` from attrs to stdlib `@dataclass(frozen=True)`.
- Add a regression test for VastAI config round-tripping.

**Non-Goals:**
- Moving `ConfigLocal` to `domain/settings.py` (P4).
- Introducing a cloud parser registry to replace the `cloud_variants` tuple (P3).
- Removing `get_private_keys` from other config classes (none have it).
- Migrating other config modules off attrs (P2–P5).
- Touching the layers contract or `package-facades` spec (the orchestrator gains a `list_private_keys_fn` callable parameter, but this does not modify the contract — it removes a would-be violation, it does not add one; `application/orchestrator.py` has zero `yascheduler.infra` imports after this change, same as before).
- Changing `ConfigLocal`'s public import path (`from yascheduler.config import ConfigLocal` still resolves after this change).

## Decisions

### Decision 1: Pure function in `infra/ssh/keys.py`, not a method

**Choice**: `list_private_keys(keys_dir: Path) -> Sequence[PurePath]` as a module-level function in a new `yascheduler/infra/ssh/keys.py`.

**Why over alternatives**:
- *Method on an SSH gateway helper class*: would require instantiating or injecting a helper; the four call sites already hold the `keys_dir` value and just need the list. A function is the smallest sufficient abstraction.
- *Keep the method, just mark it deprecated*: leaves I/O on the value object, which is the defect being fixed.

The function is pure in the sense of taking an explicit `keys_dir` argument (no hidden instance state); it still reads the filesystem, but that I/O is now named and located with the SSH infrastructure, not on a config dataclass.

**Wiring per call site, respecting the R3 layers contract**:
- `infra/cloud/manager.py`, `entrypoints/cli/manage_node.py`, `entrypoints/cli/check_status.py` import `list_private_keys` directly from `yascheduler.infra.ssh.keys` — all are at or above the `infra` layer (intra-infra, entrypoints→infra), R3-legal.
- `application/orchestrator.py` SHALL NOT import from `yascheduler.infra` (application is below infra in the layers contract). The orchestrator instead receives `list_private_keys_fn: Callable[[PurePath], Sequence[PurePath]]` as a constructor parameter and stores it as `self._list_private_keys_fn`; the `_connect_machine_consumer` call site passes `self._list_private_keys_fn` to `run_in_executor` (same shape as the prior bound-method reference `self._config.local.get_private_keys`). The composition root `yascheduler/entrypoints/di.py` imports `list_private_keys` and passes it as `list_private_keys_fn=list_private_keys` when constructing the `Orchestrator`. This keeps the application layer free of any `yascheduler.infra` import, consistent with the umbrella plan §2.3 (callable injection) and Decision Q1 in `docs/config-layer-split-plan.md`.
- This is a narrow, additive constructor change (one new keyword parameter) — not the full `Orchestrator.__init__` reshaping planned for P4 (which drops `config: Config` entirely). P1 adds the callable; P4 replaces `config` with unpacked `LocalSettings`/`RemoteDefaults`. The two changes compose without conflict.

### Decision 2: attrs→dataclass migration keeps validators in `__post_init__`

**Choice**: `ConfigLocal` becomes `@dataclass(frozen=True)`; attrs `validators.instance_of` / `validators.ge` checks move into a single `__post_init__` that raises `ValueError` on violation. The `converters.default_if_none` usage (if any) becomes explicit None-coalescing in `__post_init__` or at the parser call site.

**Why**: matches the established pattern from `queue.py::UMessage` (manual `__eq__`/`__hash__` after attrs removal) and `ssh/platform/adapters.py::RemoteMachineAdapter` (attrs→dataclass with `replace`). Keeps the class frozen and the validation local.

**Alternative considered**: move all validation into the parser (`Config.from_config_parser`) so the dataclass has no `__post_init__`. Rejected for this change because it widens scope into `config.py` parser logic; the parser-side-validation refactor is part of the broader P2–P4 parser extraction. P1 keeps validation where it is (on the class), just expressed as `__post_init__` instead of attrs validators.

### Decision 3: VastAI fix is a one-line tuple extension, not a registry

**Choice**: add `ConfigCloudVastAI` to the existing `cloud_variants` tuple in `config.py`.

**Why not a registry now**: the registry-based approach (where `infra/cloud/` exposes `CLOUD_CONFIG_PARSERS` and `Config.from_config_parser` iterates it) is the P3 design. P1 is scoped to the minimal fix that closes the latent bug without architectural change. Doing the registry here would pull P3 scope into P1 and violate the "small, no layers-contract changes" boundary. The one-line tuple addition is reversible and will be superseded by the registry in P3.

### Decision 4: `keys_dir` stays on `ConfigLocal`

**Choice**: `ConfigLocal.keys_dir: Path` remains a field. Only the `get_private_keys()` method is removed.

**Why**: the four call sites need `keys_dir` to pass to `list_private_keys()`. Removing the field would force a different storage location for the path, widening scope. The field is data; the method was I/O. Only the I/O is extracted.

## Risks / Trade-offs

- **[Risk] `ConfigLocal.__post_init__` validation drift** → Mitigation: copy the exact validator predicates from the current attrs `field(validator=...)` declarations into `__post_init__`; the existing `tests/unit/test_config.py` assertions for `ConfigLocal` defaults and overrides exercise the same validation paths.
- **[Risk] Call-site update misses a fifth caller** → Mitigation: the review already verified four call sites via grep; a follow-up grep for `get_private_keys` in `yascheduler/` after the edit must return zero matches outside the new `keys.py` (which defines `list_private_keys`, not `get_private_keys`).
- **[Risk] VastAI fix masks the deeper registry absence** → Mitigation: the design explicitly notes the registry is deferred to P3; the plan doc §4 P3 section already specifies it. The one-line fix is documented as a stopgap, not a design.
- **[Risk] `MagicMock(spec=ConfigLocal)` in tests** → Mitigation: two test files use `MagicMock(spec=ConfigLocal)` (`tests/unit/test_di.py:59`, `tests/unit/test_application_orchestrator.py:82`); neither invokes a code path that calls `get_private_keys()` through the spec mock, so removing the method does not break them. A post-edit grep for `get_private_keys` in `tests/` confirms no mock reassigns the method on a spec'd mock.
- **[Trade-off] Two sources of truth for the cloud config list** (the `__init__.py` re-exports AND the `cloud_variants` tuple) remain until P3. P1 does not consolidate them; it only makes them consistent by adding VastAI to both.