## 1. Apply spec deltas to main `openspec/specs/`

- [x] 1.1 Create `openspec/specs/config-value-objects/spec.md` from the change's `specs/config-value-objects/spec.md` (ADDED: LocalSettings, RemoteDefaults, PostgresDbConfig, Config requirements).
- [x] 1.2 Apply 14 MODIFIED-capability deltas in place: for each, replace each named requirement with the delta's new text, append ADDED requirements, delete REMOVED requirements. Specs: `cloud-config`, `cloud-providers`, `cloud-provisioner`, `config-parser-assembly`, `daemon-common`, `dependency-injection`, `domain-ports`, `package-facades`, `platform-adapters`, `postgres-schema-apply`, `postgres-uow`, `ssh-keys-loading`, `testing-unit`, `use-cases`.
- [x] 1.3 Apply the `cli-commands` MODIFIED delta (strip to_sync narrative from "CLI commands call use cases via DI"; per-command exit-code requirements retained — they carry command-specific scenarios, not pure duplication).
- [x] 1.4 Delete the 5 merged-away capability directories: `openspec/specs/app-settings/`, `db-config/`, `config-aggregate/`, `testing-infrastructure/`, `allocation-tracker/`.
- [x] 1.5 Run `openspec validate --all --json` — must pass (0 failed).

## 2. Update `AGENTS.md` OpenSpec Rule section

- [x] 2.1 Replace the 4-bullet testing-only subset with the full inventory: 31 final specs, one per line, as `` `openspec/specs/<name>` `` backticked paths (no markdown links).
- [x] 2.2 Add a terse one-line gloss only where the spec name is not self-explanatory (`config-value-objects`, `abstract-uow`); omit glosses for self-evident names.

## 3. Verify

- [x] 3.1 `openspec validate --all --json` passes after apply.
- [x] 3.2 `python3 scripts/grace_check.py` passes (no code/graph touched → expected no-change; confirms `openspec/` skip + no stray module-contract drift).
- [x] 3.3 `git diff --stat` shows changes ONLY under `openspec/specs/`, `openspec/changes/cleanup-specs-consolidate/`, and `AGENTS.md` — no `yascheduler/`, `tests/`, `docs/knowledge-graph.xml`, or `pyproject.toml` edits.
- [x] 3.4 Spot-check that no spec still references a removed symbol (`MachineGateway`, `SSHMachineGateway`, `RemoteMachineRepository`, `ConfigLocal`, `ConfigDb`, `ConfigRemote`, `PCloudConfig`, `CloudCapacity`) or a deleted package (`yascheduler.config`): `rg -n "MachineGateway|SSHMachineGateway|RemoteMachineRepository|ConfigLocal|ConfigDb|ConfigRemote|PCloudConfig|CloudCapacity|yascheduler\.config\b" openspec/specs/` returns empty. NOTE: the frozen delta's own text retains two positive-invariant mentions — `config-value-objects` "inspected for its `ConfigDb` import" scenario (tests the import resolves to `PostgresDbConfig`) and `cloud-provisioner` "There SHALL be no `PCloudConfig` Protocol" clause (asserts the Protocol's absence) — both are the delta author's deliberate wording, applied verbatim per D1; `CloudCapacity\b` (word-boundary) correctly excludes the valid `CloudCapacityExhaustedError` exception.
- [x] 3.5 Confirm the `domain-ports` "Report capacity" scenario is gone and `CloudProvisioner port` no longer mentions `capacity()` as callable.
