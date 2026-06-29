## 1. Delete migration-completion specs (Batch 1)

- [x] 1.1 Remove `openspec/specs/cloud-wrapper/` directory
- [x] 1.2 Remove `openspec/specs/remote-machine-wrapper/` directory
- [x] 1.3 Remove `openspec/specs/no-attrs-dependency/` directory
- [x] 1.4 Run `grep -rn "cloud-wrapper\|remote-machine-wrapper\|no-attrs-dependency" openspec/specs/` — expect zero live cross-references (archived changes are NOT touched)

## 2. Merge SSH trio into `ssh-infrastructure` (Batch 2)

- [x] 2.1 Create `openspec/specs/ssh-infrastructure/spec.md` by consolidating content from `ssh-gateway` + `ssh-machine-repository` + `ssh-machine-session` per the delta's `## ADDED Requirements` block (10 requirements: MachineRepository port, SSHMachineRepository implements MachineRepository, MachineSession port, SSHMachineSession implements MachineSession, Session is returned by repository and resolved per-tick by the orchestrator, MachineOperations port, SSHMachineOperations composition, download_outputs per-file SFTP isolation and retry, start_task_on_machine rolls back BUSY on failure, `_write_remote_file` re-raises non-SFTP exceptions, Backoff on session methods, SSH connection retry, Occupancy monitoring)
- [x] 2.2 De-duplicate `download_outputs` and `start_task_on_machine` contracts (kept once in `ssh-infrastructure`, with session-based signatures: `session.open_sftp()` instead of `get_sftp(ip)`, `session.occupy()`/`session.release()` instead of `repository.occupy(ip)`/`repository.release(ip)`)
- [x] 2.3 Drop transitional prose: "The system SHALL NOT provide a single `SSHMachineGateway` class" and "The `MachineGateway` Protocol in `domain/ports.py` SHALL be removed" (facts, not requirements)
- [x] 2.4 Remove `openspec/specs/ssh-gateway/`, `openspec/specs/ssh-machine-repository/`, `openspec/specs/ssh-machine-session/` directories
- [x] 2.5 Sanity-check line count: merged `ssh-infrastructure/spec.md` should be ~80-90% of the sum of the three originals (970 → ~480-580 lines after de-dup + transitional-prose removal)
- [x] 2.6 Run `grep -rn "ssh-gateway\|ssh-machine-repository\|ssh-machine-session" openspec/specs/` — expect only the `domain-ports` cross-references at lines 81/83 (fixed in Batch 4)

## 3. Merge cloud-config trio into `cloud-config` (Batch 2)

- [x] 3.1 Create `openspec/specs/cloud-config/spec.md` by consolidating `cloud-config-protocol` + `cloud-config-dtos` + `cloud-config-parsers` per the delta's `## ADDED Requirements` block (5 requirements: CloudConfig structural Protocol, Cloud config DTOs relocated to infra, Cloud config parser registry, Cloud section parser functions, Config.from_config_parser delegates cloud assembly)
- [x] 3.2 Remove `openspec/specs/cloud-config-protocol/`, `openspec/specs/cloud-config-dtos/`, `openspec/specs/cloud-config-parsers/` directories
- [x] 3.3 Run `grep -rn "cloud-config-protocol\|cloud-config-dtos\|cloud-config-parsers" openspec/specs/` — expect only the `config-parser-assembly` cross-reference at line 59 (fixed in Batch 4)

## 4. Absorb persistence-exception specs into `domain-exceptions` (Batch 3)

- [x] 4.1 Add `UnitOfWorkNotInitializedError exception class` requirement to `openspec/specs/domain-exceptions/spec.md` (content from the delta's `## ADDED Requirements`)
- [x] 4.2 Add `TaskRowNotFoundError exception class` requirement to `openspec/specs/domain-exceptions/spec.md` (content from the delta's `## ADDED Requirements`)
- [x] 4.3 Remove `openspec/specs/uow-not-initialized-error/` and `openspec/specs/task-row-not-found-error/` directories
- [x] 4.4 Run `grep -rn "uow-not-initialized-error\|task-row-not-found-error" openspec/specs/` — expect zero live cross-references

## 5. Apply D5 substitution table to modified specs (Batch 4)

- [x] 5.1 `orchestrator`: apply the 5 MODIFIED requirements from the delta — replace `gateway: MachineGateway` with `repository: MachineRepository` + `operations: MachineOperations` in `Orchestrator manages producer-consumer loops`, `Allocate loop`, `Consume loop`, `Deallocate loop`, `Connect machine loop`; replace `gateway.connect(...)`→`repository.connect(...)`, `gateway.list_connected()`→`repository.list_connected()`, `gateway.disconnect_all()`→`repository.disconnect_all()`, `gateway.items()`→`repository.list_connected()`
- [x] 5.2 `use-cases`: apply the 4 MODIFIED requirements — `AllocateTask`, `ConsumeTask`, `DeallocateIdleNodes`, `AbandonNode`; replace `gateway: MachineGateway` params with `repository` + `operations`; replace `gateway.download_outputs()`→`operations.download_outputs(session, ...)`; replace `gateway.disconnect`→`repository.disconnect`; drop the `RemoteMachineRepository` historical name-drop in `DeallocateIdleNodes`
- [x] 5.3 `cloud-provisioner`: apply the 1 MODIFIED requirement — `CloudProvisionerImpl.stop closes machine_gateway connections`; rename `machine_gateway`→`machine_repository`, `SSHMachineGateway`→`SSHMachineRepository`, `_machines`→`_sessions`, `disconnect_all` on the repository
- [x] 5.4 `testing-unit`: apply the 1 MODIFIED requirement — `Remote machine management`; replace `RemoteMachineMetadata`/`is_free_longer_than`/`RemoteMachineRepository.filter` with `ConnectedMachine`/`MachineSession.occupy()`/`MachineSession.release()`/`SSHMachineRepository.list_free(platforms)`
- [x] 5.5 `dependency-injection`: apply the 2 MODIFIED requirements — `make_daemon factory` (drop `DB`/`RemoteMachineRepository` name-drops in the `make_daemon returns orchestrator with UoW factory` scenario) and `make_daemon shares one SSHMachineGateway on the production path` (rename requirement title to `make_daemon shares one SSHMachineRepository on the production path`; replace `_machines`→`_sessions`, `machine_gateway`→`machine_repository`)
- [x] 5.6 `package-facades`: apply the 2 MODIFIED requirements — `Extended facade contents` (replace `adapters.cli.init`→`entrypoints.cli.init`, `adapters.cli.manage_node`→`entrypoints.cli.manage_node`, `adapters.cli.daemonize`→`entrypoints.cli.daemonize`, `adapters.persistence.postgres_uow`→`infra.persistence.postgres_uow`, `adapters` LAYER facade→`infra` LAYER facade; replace `SSHMachineGateway` re-export with `SSHMachineRepository` + `SSHMachineOperations`) and `Documented private-symbol carve-outs` (replace `from .adapters.cloud.adapters import _resolve_adapter`→`from .infra.cloud.adapters import _resolve_adapter`)
- [x] 5.7 `cli-commands`: apply the 8 MODIFIED requirements + 1 REMOVED requirement per the delta — replace `SSHMachineGateway`→`SSHMachineRepository`/`SSHMachineOperations` in `CLI commands call use cases via DI`, `yasetnode gateway lifecycle and resource safety`, `yastatus view mode connects via SSH`; replace `@to_sync`-decorated async with `def f(argv): asyncio.run(_f_async(argv))` in `yasubmit parses AiiDA script`, `yanodes lists nodes`, `yasetnode module path and GRACE-lite markup`, `yastatus queries task status`; remove the `utils.py preserves re-exports` requirement entirely; replace `adapters.cli.commands`→`entrypoints.cli`
- [x] 5.8 `cloud-providers`: apply the 1 MODIFIED requirement — `Provider code relocated`; replace `adapters.cloud.providers.az/hetzner/upcloud`→`infra.cloud.providers.*` in the 3 provider-accessible scenarios
- [x] 5.9 `platform-adapters`: apply the 1 MODIFIED requirement — `Platform code relocated`; replace `adapters.ssh.platform.adapters/checks/linux`→`infra.ssh.platform.*` in the 3 accessible scenarios
- [x] 5.10 `config-parser-assembly`: apply the 1 MODIFIED requirement — `parse_config assembly`; replace the `cloud-config-dtos` capability cross-reference at line 59 with `cloud-config` (the merged capability name)
- [x] 5.11 `domain-ports`: apply the 1 MODIFIED requirement — `MachineRepository, MachineSession, and MachineOperations ports replace MachineGateway`; replace `ssh-machine-repository` capability cross-reference at line 81 with `ssh-infrastructure`; replace `ssh-machine-session` capability cross-reference at line 83 with `ssh-infrastructure`
- [x] 5.12 `domain-exceptions`: apply the 1 MODIFIED requirement — `CloudError is not re-exported from yascheduler.infra.cloud`; replace `adapters.cloud does not re-export CloudError`→`infra.cloud does not re-export CloudError` and `adapters.cloud still re-exports`→`infra.cloud still re-exports` in the 2 scenarios (the 2 ADDED persistence-exception requirements were applied in Batch 3)

## 6. Post-edit grep sweep (Batch 4 verification)

- [x] 6.1 Run `grep -rn "SSHMachineGateway\b\|MachineGateway\b" openspec/specs/` — expect zero matches
- [x] 6.2 Run `grep -rn "adapters\.cli\|adapters\.ssh\|adapters\.cloud\|adapters\.persistence\|adapters\.notifier" openspec/specs/` — expect zero matches (the R3 layer-direction contract in `package-facades` already uses `yascheduler.infra`/`yascheduler.entrypoints`)
- [x] 6.3 Run `grep -rn "@to_sync" openspec/specs/cli-commands/spec.md` — expect zero matches (all per-command requirements now say `asyncio.run`)
- [x] 6.4 Run `grep -rn "utils\.py\|RemoteMachineRepository\|RemoteMachineMetadata\|is_free_longer_than" openspec/specs/` — expect zero matches
- [x] 6.5 Run `grep -rn "ssh-gateway\|ssh-machine-repository\|ssh-machine-session\|cloud-config-protocol\|cloud-config-dtos\|cloud-config-parsers\|cloud-wrapper\|remote-machine-wrapper\|no-attrs-dependency\|uow-not-initialized-error\|task-row-not-found-error" openspec/specs/` — expect zero matches (all deleted/merged spec names gone from live specs)

## 7. Update knowledge graph (Batch 6)

- [x] 7.1 In `docs/knowledge-graph.xml`, update the `<path>` field of the M-SSH module record to point at `openspec/specs/ssh-infrastructure/spec.md` (replacing the prior `ssh-gateway`/`ssh-machine-repository`/`ssh-machine-session` references)
- [x] 7.2 Update the `<path>` field of the M-CLOUDCONFIG module record to point at `openspec/specs/cloud-config/spec.md` (replacing the prior `cloud-config-protocol`/`cloud-config-dtos`/`cloud-config-parsers` references)
- [x] 7.3 Do NOT rename any M-ID; do NOT change `<depends>`; do NOT add/remove `<CrossLink>` entries (only spec-file references change)
- [x] 7.4 Run `python3 scripts/grace_check.py` — expect exit 0

## 8. Final validation (Batch 7)

- [x] 8.1 Run `openspec validate --all --json` — expect exit 0, all `valid: true`, no errors
- [x] 8.2 Run `python3 scripts/grace_check.py` — expect exit 0
- [x] 8.3 Run `uv run ruff check .` and `uv run ruff format --check .` — expect no new issues (specs-only change should not affect Python linting, but verify nothing broke)
- [x] 8.4 Confirm `git status` shows only `openspec/specs/` deletions/additions and `docs/knowledge-graph.xml` modification — no `yascheduler/` or `tests/` or `pyproject.toml` changes
- [x] 8.5 Final spec count: 34 (down from 43); final line count: ~6300 (down from 8198)