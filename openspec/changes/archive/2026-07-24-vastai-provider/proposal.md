## Why

`yascheduler` schedules scientific GPU workloads, but its cloud-provider roster
(Hetzner, Upcloud, Azure) covers only CPU/low-GPU VMs. Vast.ai (the GPU
marketplace; in code and config it is referred to as "VastAI") offers
on-demand GPU instances suitable for the GPU workloads the scheduler targets.
A prior VastAI adapter attempt was architecturally unsound and has been
removed; the provider wiring already in place
(`get_vastai_adapter` in `adapters.py`, `ConfigCloudVastAI`, the INI parser,
the `CLOUD_ADAPTER_GETTERS` registry entry) references `vastai_create_node` /
`vastai_delete_node` functions that do not exist on disk, so the provider is
currently dead code that breaks import on demand. A conformant adapter is
needed to make VastAI a working provider.

## What Changes

- Add a new VastAI provider module implementing the
  `CreateNodeCallable` / `DeleteNodeCallable` contracts:
  `vastai_create_node` (register account-level SSH key if absent → search
  offers per config → take a random offer from the top-5 cheapest → create
  instance → poll until `running` → return `CloudCreateNodeDTO`) and
  `vastai_delete_node` (delete instance by instance id).
- `external_id` SHALL be the VastAI instance id (the identifier issued by
  VastAI at instance creation), NOT the IP address. This corrects the prior
  incorrect requirement in the `cloud` spec that grouped VastAI with the
  IP-identity providers; deletion identifies the instance by this id.
- Bridge the cloud-init contract to VastAI's `onstart` script, since VastAI
  has no cloud-init support. `vastai_create_node` SHALL translate the
  `CloudInitConfig` it receives into an `onstart` bash script when the operator
  has NOT supplied a custom startup script in config (`onstart_script`):
  `package_upgrade` → package-manager upgrade, `packages` → package install,
  `bootcmd` → appended commands. The package manager SHALL be detected from
  the image (apt-get for Debian/Ubuntu images, dnf otherwise). When a custom
  `onstart_script` is configured, it is used verbatim and the `CloudInitConfig`
  translation is skipped.
- Auto-detect KVM/VM vs Docker launch mode from the configured `image`: images
  whose name contains `vastai/kvm` use VM mode (`vm: true`, runtype
  `ssh_proxy`, onstart requires `#!/bin/bash` shebang); all other images use
  Docker mode (`vm` absent/false, onstart is a plain bash script). No separate
  `vastai_vm` config flag is introduced.
- Define a dedicated VastAI exception hierarchy (distinct types per failure
  mode: auth, no offers found, instance creation, instance polling timeout,
  instance terminal status, delete, SSH key registration, HTTP transport). Each
  exception carries a free-form message and an optional `status: int | None`
  field for HTTP status code context.
- Add structured block-boundary log tracing (`logger.debug("BLOCK",
  extra={...})`) on every significant branch.
- Add unit tests (DTO shape, exception types, offer selection, onstart
  generation, KVM/Docker detection, delete) and an env-gated e2e test against a
  live VastAI account, modeled on the Hetzner e2e test.
- Declare the `aiohttp` and `backoff` dependencies. Rationale: VastAI exposes
  a REST API over HTTPS and the adapter runs inside the scheduler's async event
  loop; `aiohttp` is the established async HTTP client in the Python ecosystem
  and matches the project's async-first architecture, so no thread-pool offload
  (as the sync-SDK providers require) is needed. `backoff` provides fibonacci
  retry for VastAI's rate-limit (429) responses.
- Non-goals: no retry to a different offer within a single `create_node` call
  on terminal instance status — the next scheduler allocation cycle retries
  with a fresh offer search; no support for spot/interruptible pricing (on-demand
  only); no pause/resume (instance deletion only); no changes to other cloud
  providers; no separate `vastai_vm` config flag (KVM/Docker auto-detected).
- Update `docs/VASTAI.md` to document the actual adapter behavior and config.

## Capabilities

### New Capabilities
- `vastai-provider`: VastAI cloud provider adapter — account-level SSH key
  registration, offer search by GPU/VRAM/price/disk criteria, random selection
  from top-5 cheapest offers (avoids repeated allocation to the same broken
  provider), instance creation (Docker and KVM launch modes with `ssh_proxy`
  runtype), readiness polling, cloud-init-to-onstart translation with
  package-manager detection, instance deletion by instance id, instance listing
  by label (for e2e cleanup), dedicated exception hierarchy with HTTP status
  code context, structured log tracing, fibonacci-backoff retry on rate-limit
  (429) responses.

### Modified Capabilities
- `cloud`: Correct the VastAI `external_id` contract — `external_id` SHALL be
  the VastAI instance id, not the IP address; deletion SHALL identify the
  instance by `external_id`. The prior requirement grouping VastAI with the
  IP-identity providers (Azure, Upcloud) was incorrect.

## Impact

- **New code**: `yascheduler/infra/cloud/providers/vastai.py` (adapter module
  with `vastai_create_node`, `vastai_delete_node`, SSH-key registration, offer
  search, onstart generation, exception types).
- **Existing code**: `yascheduler/infra/cloud/adapters.py` already wires
  `get_vastai_adapter`; no change expected beyond the provider module becoming
  importable. `ConfigCloudVastAI` and the INI parser in `config_parser.py` may
  receive minor adjustments if config gaps surface during implementation.
- **Specs**: `openspec/specs/cloud/spec.md` modified (VastAI external_id
  correction); new `openspec/changes/vastai-provider/specs/vastai-provider/spec.md`.
- **Tests**: new unit tests in `tests/unit/` (provider DTO, exceptions, offer
  selection, onstart generation, mode detection, delete); new env-gated e2e in
  `tests/e2e/` modeled on `test_hetzner_live.py`; existing VastAI stubs in
  `tests/unit/test_cloud_provider_create_delete.py` rewritten to match the real
  contract.
- **Docs**: `docs/VASTAI.md` rewritten to match adapter behavior and config.
- **Dependencies**: `aiohttp` added (HTTP client for the VastAI REST API);
  `backoff` added (fibonacci retry for rate-limit responses).
- **Other providers**: untouched.