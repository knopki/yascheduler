## Context

`yascheduler` schedules scientific GPU workloads across cloud providers. Its
provider roster (Hetzner, Upcloud, Azure) covers only CPU/low-GPU VMs. VastAI is
a GPU marketplace with on-demand GPU instances accessed via an async REST API
(`aiohttp`), no cloud-init support, and asynchronous instance creation (instance
id is returned immediately, readiness is reached via polling).

A prior VastAI adapter attempt was architecturally unsound and has been removed.
Provider wiring already in place — `get_vastai_adapter` in
`yascheduler/infra/cloud/adapters.py` (registered in `CLOUD_ADAPTER_GETTERS`),
`ConfigCloudVastAI` and the INI parser in `config_parser.py`, the
`CLOUD_CONFIG_PARSERS` registry entry — references `vastai_create_node` /
`vastai_delete_node` functions that do not exist on disk, so the provider is
currently dead code that breaks import on demand.

This change adds the missing provider module. The contract is the same
`CreateNodeCallable` / `DeleteNodeCallable` the other providers satisfy; VastAI
adds provider-specific config fields (`onstart_script`, `docker_options`, GPU
search criteria) and a cloud-init-to-`onstart` translation because VastAI has no
cloud-init.

## Goals / Non-Goals

**Goals:**
- A working VastAI provider implementing `vastai_create_node` and
  `vastai_delete_node` against the shared `CloudAdapter` contract.
- Account-level SSH key registration with presence check (no duplicate).
- Cheapest-compatible-offer search and selection by configured GPU/VRAM/price
  criteria.
- Both Docker and KVM/VM launch modes auto-detected from the image.
- Cloud-init-to-`onstart` translation with package-manager detection, overridable
  by a custom startup script.
- A dedicated VastAI exception hierarchy with distinct types per failure mode.
- Structured block-boundary log tracing on every significant branch, secrets
  redacted.
- Unit and env-gated e2e tests modeled on the Hetzner reference.

**Non-Goals:**
- Retry against a different offer within a single `create_node` call on terminal
  instance status — the next scheduler allocation cycle retries with a fresh
  offer search.
- Spot/interruptible pricing (on-demand only).
- Pause/resume (instance deletion only).
- Changes to other cloud providers.
- DB schema changes or migrations.
- Metrics/alerting beyond existing daemon logging.

## Decisions

### Architecture

**Form**: single-file provider module
`yascheduler/infra/cloud/providers/vastai.py` (not a package), following the
`az.py` / `hetzner.py` / `upcloud.py` convention. No classes; module-level async
functions.

**GRACE top-down structure (architectural decision)**: the module SHALL be built
in strict top-down order with full GRACE semantic markup, not ad-hoc regions.
This ordering is a load-bearing constraint — skipping it breaks the unit-test
discipline (stubs before bodies, tests against contracts). The module SHALL be
authored in this sequence, and the tasks phase SHALL enforce it:

1. **`# region MODULE_CONTRACT`** — file-level contract first. Fields:
   `PURPOSE` (VastAI provider lifecycle: SSH key registration, offer search,
   cheapest selection, instance create/poll, delete), `SCOPE` (cloud-side
   lifecycle only; NOT: DB, UoW, SSH setup, allocator), `DEPENDENCIES` (`USES
   API: cloud.vast.ai (aiohttp)`, `ConfigCloudVastAI`, `CloudInitConfig`,
   `CloudCreateNodeDTO`, `SSHKey`), `KEYWORDS`.
2. **Exception hierarchy** — `VastAIError` (root, carries `status: int | None`
   for HTTP status code context) and subclasses. Defined before functions
   because `vastai_create_node`/`vastai_delete_node` raise them.
3. **Private HTTP helpers** — `_request` (single HTTP entry point, raises
   `VastAIError` on non-2xx or bad JSON), `_request_with_retry` (wraps `_request`
   with fibonacci backoff on 429 rate-limit, up to 60s).
4. **SSH key helpers** — `_list_ssh_keys`, `_create_ssh_key`, `ensure_ssh_key`
   (public by name, not in `__all__`). Each with `# region FUNC_<name>`.
5. **Offer helpers** — `search_offers`, `select_cheapest_offer`,
   `generate_onstart`, `detect_launch_mode`. Each with `# region FUNC_<name>`.
6. **Instance lifecycle helpers** — `_create_instance`, `_show_instance`,
   `_best_effort_delete`, `wait_until_ready`. Each with `# region FUNC_<name>`.
7. **Public callables** — `vastai_create_node`, `vastai_delete_node`,
   `vastai_list_instances`. Each with `# region FUNC_<name>`.
8. **Unit tests against contracts** — written against the stubs (public
   callable orchestration shape, exception subclass relations, DTO mapping,
   pure helper behavior: `select_cheapest_offer`, `generate_onstart`,
   `detect_launch_mode`).
9. **Implementation inside the contracted regions** — fill the stub bodies; add
   `# region BLOCK_<name>` for non-trivial inner steps (the orchestration
   sequence in `vastai_create_node`, the polling loop in `wait_until_ready`,
   the onstart assembly in `generate_onstart`). Block-boundary
   `logger.debug("BLOCK", extra={...})` at each step.

Each public function and helper is wrapped in its own `# region`/`# endregion`;
each non-trivial inner step gets a `# region BLOCK_<name>`. `__all__` lists only
the public API (`vastai_create_node`, `vastai_delete_node`,
`vastai_list_instances`); helpers are private by `_` prefix convention and
omission from `__all__`.

**Layers**:
- Public callables (`__all__`): `vastai_create_node`, `vastai_delete_node`,
  `vastai_list_instances`.
- Helpers (private by `_` prefix and omission from `__all__`): `_request`,
  `_request_with_retry`, `_list_ssh_keys`, `_create_ssh_key`, `_create_instance`,
  `_show_instance`, `_best_effort_delete`, plus the TypeGuard functions.
- Public-by-name helpers (no `_` prefix, not in `__all__`): `ensure_ssh_key`,
  `search_offers`, `select_cheapest_offer`, `generate_onstart`,
  `detect_launch_mode`, `wait_until_ready`.
- Exceptions: `VastAIError` (root, carries `status: int | None`) and subclasses,
  not in `__all__` (imported by name from the module).

**External integration**: VastAI REST API via `aiohttp` with `backoff` for
fibonacci retry on rate-limit (429) responses; the shared `CloudAdapter` contract
(`CreateNodeCallable` / `DeleteNodeCallable`); existing `ConfigCloudVastAI` and
INI parser. The module never touches the DB, UoW, or SSH setup — those live in
`CloudProvisionerImpl.allocate` / `_setup_vm` after `create_node` returns the
DTO.

**Boundary**: provider-internal lifecycle only — cloud-side VM create/delete and
readiness. No scheduler/allocator logic.

### Component Structure

Public (`__all__`): `vastai_create_node`, `vastai_delete_node`,
`VastAIError`, `VastAIDeleteError`, `VastAINoOffersError`,
`VastAIInvalidOfferError`, `VastAIInstanceCreateError`.

Helpers (without `_` prefix, not in `__all__`):

| Helper                    | Responsibility                                                                                                                                                                                |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_request`                | Single HTTP entry point: `session.request(...)` → status check → JSON parse → raise `VastAIError` on non-2xx or bad shape. Reused by all helpers. Private (`_` prefix).                        |
| `_request_with_retry`     | Wraps `_request` with fibonacci backoff on 429 (rate-limit), up to 60s. Private.                                                                                                               |
| `_list_ssh_keys`          | GET /ssh/ → list of registered SSH keys. Private.                                                                                                                                             |
| `_create_ssh_key`         | POST /ssh/ with public key. Returns bool success. Private.                                                                                                                                    |
| `ensure_ssh_key`          | GET /ssh/ presence check by public key → POST /ssh/ if absent. Returns bool (True if key present or registered).                                                                              |
| `search_offers`           | POST /bundles/ with the fixed filter body (gpu_ram gte, num_gpus eq, gpu_frac gte 1.0, reliability gte 0.99, rentable eq true, rented eq false, dph_total lte max_price, type on-demand, order dph_total asc, limit 20). Returns list of offers. |
| `select_cheapest_offer`   | Random selection from top-5 cheapest offers (avoids repeated allocation to the same broken provider). Empty list → `VastAINoOffersError`. Price violating constraint → `VastAIInvalidOfferError`. |
| `generate_onstart`        | Custom `cfg.onstart_script` verbatim if non-empty; otherwise cloud-init translation (package_upgrade → upgrade, packages → install, bootcmd → appended commands, list items extended) with package-manager detection (apt-get for Debian/Ubuntu images, dnf otherwise). KVM images get `#!/bin/bash` shebang. |
| `detect_launch_mode`      | `"kvm"` if `cfg.image` contains `vastai/kvm`, else `"docker"`. Synchronous (not async).                                                                                                        |
| `_create_instance`        | PUT /asks/{offer.id}/ with image, disk, runtype `ssh_proxy`, target_state `running`, cancel_unavail True, vm flag, env, onstart. Returns instance id (int). Private.                          |
| `_show_instance`          | GET /instances/{id}/ → instance dict with actual_status, ssh_host, ssh_port. Private.                                                                                                          |
| `_best_effort_delete`     | Best-effort DELETE of instance id (swallows VastAIError). Private.                                                                                                                             |
| `wait_until_ready`        | Poll GET /instances/{id}/ until ready. Bounded by `create_node_timeout`. Terminal status (stopped/frozen/exited/unknown/offline) or timeout → `VastAIInstanceCreateError`; on timeout/terminal, best-effort DELETE of the known instance id to prevent orphans, then raise. |

All async helpers take `session: aiohttp.ClientSession` as the first parameter
(plus their specific arguments). `vastai_create_node` owns the
`async with aiohttp.ClientSession()` and passes the session down; the session
is guaranteed closed by the `async with` regardless of success/failure.
`vastai_delete_node` and `vastai_list_instances` each own their own session.

### Session Lifecycle

`async with aiohttp.ClientSession()` scoped inside each public callable (one
session per `create_node` / `delete_node` call), passed to helpers by parameter.
No `@cache`-d module-level session — a cached session would not be closed before
event-loop shutdown, causing "Unclosed client session". The `async with` block
guarantees close on all paths. One `create_node` call issues ~5-7 requests
(key-list, key-register?, search, create, poll×N) reusing the session's
connection pool within the call.

### Data Flow

create_node (input → output):

```
cfg: ConfigCloudVastAI, key: SSHKey, cloud_config: CloudInitConfig | None
  │
  ├─ ensure_ssh_key(session, key.export_public_key())
  │    └─ GET /ssh/ → list keys; POST /ssh/ if absent; returns bool
  │
  ├─ offers = search_offers(session, cfg)
  │    └─ POST /bundles/ with filter body → list[offer]
  │
  ├─ offer = select_cheapest_offer(offers, cfg.max_price_per_hr)
  │    └─ random.choice(sorted(offers, key=dph_total)[:5]) or VastAINoOffersError
  │
  ├─ onstart = generate_onstart(cfg, cloud_config)
  │    └─ cfg.onstart_script verbatim | translation with pm detection
  │
  ├─ mode = detect_launch_mode(cfg.image) → "kvm" | "docker"  (sync)
  │
  ├─ instance_id = _create_instance(session, offer.id, image, disk, env, vm, onstart)
  │    └─ PUT /asks/{offer.id}/  {image, disk, runtype: ssh_proxy,
  │       target_state: running, cancel_unavail: True, vm, env, onstart}
  │    └─ returns int(new_contract)
  │
  ├─ inst = wait_until_ready(session, instance_id, cfg.connect_grace)
  │    └─ poll GET /instances/{id}/ until running; ssh_host/ssh_port
  │    └─ terminal: stopped/frozen/exited/unknown/offline
  │
  └─ CloudCreateNodeDTO(
       external_id = str(instance_id),
       hostname = inst.ssh_host,
       port = int(inst.ssh_port),
       username = "root",
       jump_host/port/username = cfg.*
     )
```

delete_node: `cfg` + `external_id` → `DELETE /instances/{external_id}/` → None.
Idempotent: a 404 / already-deleted indication returns without raising.

**State**: none in the module. The `aiohttp.ClientSession` is local to the
`async with` inside each public callable. No module-level mutables, caches, or
globals. All data flows through helper parameters and return values.

**Secrets**: `cfg.api_key` → `Authorization: Bearer <key>` header only. It never
enters log fields (redaction). The public SSH key is not a secret.

### Error Handling / Failure Modes

VastAI exceptions (provider-internal, all subclass `VastAIError`):
`VastAIError` (root: auth failure 401/403, HTTP transport/aiohttp ClientError,
unexpected response shape, SSH-key registration failure; carries
`status: int | None` for HTTP status code context), `VastAIDeleteError`
(DELETE failed or non-idempotent real error — not 404), `VastAINoOffersError`
(empty search result), `VastAIInvalidOfferError` (offer missing `id` or price
violates the constraint), `VastAIInstanceCreateError` (`PUT /asks/` failure,
polling timeout, terminal status).

Failure flow:

| Failure                                | Caught where              | Raised                      | Behavior                              |
| -------------------------------------- | ------------------------- | --------------------------- | ------------------------------------- |
| aiohttp HTTP error / non-2xx           | `_request` helper         | `VastAIError` (transport)   | propagates up through create/delete   |
| 401/403 auth                           | `_request` helper         | `VastAIError`               | propagates                             |
| 429 rate-limit                         | `_request_with_retry`     | `VastAIError` (after retry) | fibonacci backoff up to 60s, then raise |
| SSH-key GET/POST failure               | `ensure_ssh_key`          | `VastAIError`               | propagates                             |
| Empty offers                           | `select_cheapest_offer`   | `VastAINoOffersError`       | propagates                             |
| Offer price over limit                 | `select_cheapest_offer`   | `VastAIInvalidOfferError`   | propagates                             |
| `PUT /asks/` non-success               | `_create_instance`        | `VastAIError`               | propagates                             |
| Polling timeout (`connect_grace`)      | `wait_until_ready`        | `VastAIInstanceCreateError` | best-effort DELETE of instance id, then raise (no in-call retry — non-goal) |
| Terminal status (stopped/frozen/exited/unknown/offline) | `wait_until_ready` | `VastAIInstanceCreateError` | best-effort DELETE, then raise         |
| DELETE non-2xx / unexpected            | `vastai_delete_node`      | `VastAIDeleteError`         | propagates                             |
| DELETE 404 / already-deleted           | `vastai_delete_node`      | (no exception)              | idempotent return                     |

**External boundary**: `CloudProvisionerImpl.allocate`
(`yascheduler/infra/cloud/manager.py:131-141`) wraps ANY `create_node`
exception in `CloudAllocateError`. Setup-failure cleanup (manager:182/198) only
fires when a DTO was returned (setup failed after successful create). A failure
before the DTO is returned leaves no external_id for the provisioner to clean
up — the provider's `wait_until_ready` mitigates this by best-effort deleting
the known instance id before raising on timeout/terminal status.

**Observability**: every raise is accompanied by a block-marker log with
structured fields (instance_id/offer_id/status). The API key never appears in
log fields.

### Testing Approach

Pyramid (per AGENTS.md: unit for core logic; integration/e2e for cloud
lifecycle; VastAI is HTTP-only, real server only in e2e):

| Layer  | What                                                                                                                                                       | Infrastructure                                                  |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Unit   | Pure helper logic without HTTP: `select_cheapest_offer` (empty/non-empty/random top-5/price over limit), `generate_onstart` (custom verbatim / translation / pm apt-get vs dnf / bootcmd list items extended / KVM shebang), `detect_launch_mode` (kvm/docker by image substring) | mocks, no network                                               |
| Unit   | Exception hierarchy: subclass relationships, free-form message, `status` field on `VastAIError`                                                           | pure                                                            |
| Unit   | DTO shape: `vastai_create_node` returns `CloudCreateNodeDTO` with external_id=instance_id, hostname=ssh_host, port=ssh_port, username=root                  | mock `aiohttp.ClientSession` (hetzner mock pattern)             |
| Unit   | Idempotent delete: 404/already-deleted → no raise                                                                                                          | mock session                                                    |
| Unit   | Log tracing: block markers on key/search/select/create/poll/ready/delete, secrets redacted (api_key absent from fields)                                   | `log_records` fixture + `tests/log_assertions.py`             |
| Unit   | Orphan cleanup: `wait_until_ready` timeout/terminal → best-effort DELETE of instance_id issued, then `VastAIInstanceCreateError` raised                    | mock session                                                    |
| Unit   | `vastai_list_instances`: returns instances matching cfg.label                                                                                             | mock session                                                    |
| E2E    | Live VastAI account: full cycle submit→autoscale→allocate→download→DONE→idle-deallocate. Env-gated (`YASCHEDULER_TEST_VASTAI=1` + `VAST_API_KEY`). Strong cleanup-with-loud-fail in finally: best-effort delete every observed instance id, then assert each is gone via a real `GET /instances/{id}/` oracle (404 expected) — a survivor fails the test loudly. Asserts CLOUD_DONE/CLOUD_DELETE log records and a cloud==vastai node appears in the DB. Uses `vastai_list_instances` to find orphaned instances by label. | real VastAI API, no testcontainer (HTTP-only provider)         |

**E2E specifics vs Hetzner reference**: like the Hetzner live test, the VastAI
e2e runs against a real provider account (env-gated, run manually, not in every
CI pass). It adapts the hetzner shape to VastAI: wider timeouts (GPU image pull +
setup), a stricter env gate (GPU billing), and a provider-native deletion oracle
(`GET /instances/{id}/` → 404) instead of the hetzner `client.servers.get_by_id`
oracle. The full-cycle shape (submit → node appears → jobs DONE → idle deallocate
→ strong deletion assert) is preserved; the provider-facing verification is
VastAI-native.

**Hard-to-test**: real polling (depends on provider cold-start ~minutes) → e2e
only; orphan-instance scenario → unit via mock returning terminal-status;
onstart-script content → unit via inspecting the generated string (not via a
real instance).

**Test locations**: a new VastAI unit test module (helpers, exceptions, DTO,
logs, orphan); the existing VastAI create/delete stubs in the shared
create-delete test module are rewritten to match the real contract (instance_id,
not IP); a new env-gated VastAI e2e test modeled on the Hetzner live test.

**Logs**: tests use the project's `log_records` fixture + `extra_fields()` log
assertion helper (as the hetzner e2e does with `_assert_cloud_done_log` /
`_assert_cloud_delete_log`) to assert block-marker scenario progression.

### Performance

One `create_node` call = ~5-7 HTTP requests within a single
`aiohttp.ClientSession` (connection reuse inside the call). Polling iterates
within `connect_grace` / 5s poll-interval. The existing `op_limit=1` semaphore
in `get_vastai_adapter` prevents concurrent creates. Rate-limit (429) responses
trigger fibonacci backoff up to 60s via `backoff`. Low risk.

### Security

The API key travels in the `Authorization: Bearer <key>` header only and is
redacted from log fields (spec requirement). The public SSH key is not a secret.
Requests to the provider originate only from the daemon. Low risk.

## Migration Plan

No DB schema change (the `yascheduler_nodes` table already carries `external_id`
and `cloud`; `ConfigCloudVastAI` and the INI parser already exist). No config
breaking change (existing vastai INI keys are preserved).

**Deploy**: the `vastai.py` module appears on disk → `get_vastai_adapter`
(already registered in `CLOUD_ADAPTER_GETTERS`) becomes importable → the provider
activates when `[clouds]` contains a `vastai_api_key`. Without a vastai config,
`select_provider_pure` never selects it — zero effect on existing deployments.

**Rollback**: remove `vastai.py` → `get_vastai_adapter` raises on import only when
a vastai config is present. Without vastai config, rollback is a no-op (the
provider is never selected). No data migration to reverse.

**Breaking**: none user-facing. The existing VastAI create/delete stubs in the
shared create-delete test module are rewritten to match the real contract
(instance_id, not IP) — test-only, not user-facing.

## Risks / Trade-offs

- **Orphan instance on polling failure** → `wait_until_ready` best-effort DELETEs
  the known instance id (from the `PUT /asks/` response) before raising on
  timeout or terminal status. Mitigates billing for an instance the provisioner
  cannot clean up (no DTO returned). Best-effort: if the DELETE itself fails,
  the instance is orphaned and billed — logged via a block marker for manual
  cleanup.
- **No in-call retry on terminal status** → accepted (non-goal). A failed offer
  surfaces as `VastAIInstanceCreateError`; the next scheduler allocation cycle
  retries with a fresh search. Trade-off: simpler adapter vs. longer
  time-to-first-node on transient provider failures.
- **Cloud-init translation is best-effort** → VastAI has no cloud-init; the
  translation maps `package_upgrade`, `packages`, `bootcmd` to an `onstart`
  script. Fields beyond these (e.g. `runcmd`, `write_files`) are not translated.
  Trade-off: covers the scheduler's actual usage (engine packages + upgrade)
  vs. a full cloud-init engine. A custom `onstart_script` overrides the
  translation entirely when full control is needed.
- **Package-manager detection heuristic** → apt-get for Debian/Ubuntu-derived
  images, dnf otherwise. A non-Debian/Ubuntu image without dnf would fail at
  runtime inside the instance. Trade-off: covers the common GPU base images
  (pytorch, vastai/kvm ubuntu) vs. exhaustive distro detection. Overridable by a
  custom `onstart_script`.
- **Idempotent delete relies on 404 semantics** → the adapter treats a 404 /
  already-deleted indication as success. If VastAI returns a non-404 error for a
  missing instance, `VastAIDeleteError` is raised. Trade-off: matches the
  documented API; verified in the e2e cleanup path.
- **E2E costs money and time** → the live e2e spawns a real GPU instance (billed,
  minutes to cold-start), same opt-in/manual-run discipline as the Hetzner live
  test. Mitigation: strict env gate (`YASCHEDULER_TEST_VASTAI=1` + key) — the test
  is skipped by default and run only on explicit opt-in; strong finally cleanup
  with a native deletion oracle (`GET /instances/{id}/` → 404) fails loudly on
  any leaked instance, so a billing leak cannot pass silently. Trade-off: e2e is
  opt-in and slower, not run on every CI pass.
