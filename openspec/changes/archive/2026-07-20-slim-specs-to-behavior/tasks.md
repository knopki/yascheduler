## 1. Slim LocalSettings spec (config-value-objects)

- [x] 1.1 Drop the "legacy [local] cloud_package_upgrade warns as unknown" scenario from `openspec/specs/config-value-objects/spec.md` under the LocalSettings value object requirement — the relocation is finalized and the "LocalSettings has no cloud_package_upgrade field" scenario already covers the contract.
- [x] 1.2 Confirm `openspec validate config-value-objects --json` reports `valid: true` and `uv run pytest -m unit` for the config-parsing tests still passes.

## 2. Slim E2E test fixtures spec (e2e-testing)

- [x] 2.1 In `openspec/specs/e2e-testing/spec.md`, merge the two `log_records` propagation scenarios into a single capture+teardown scenario whose `GIVEN` line defers the descendant-propagation contract to the `logging` capability, and add the one-line deferral to the requirement body.
- [x] 2.2 Confirm `openspec validate e2e-testing --json` reports `valid: true` and the e2e `log_records` fixture behavior still matches the kept scenario.

## 3. Slim LogFormatter spec (logging)

- [x] 3.1 Drop the "native LogRecord attribute set is derived by introspection" and "package prefix is derived from the formatter module name" implementation-hint scenarios from `openspec/specs/logging/spec.md` under the LogFormatter requirement — both describe code-internal mechanics.
- [x] 3.2 Verify `yascheduler/shared/log.py` `MODULE_CONTRACT` already carries both facts (introspection derivation, package-prefix derivation); enrich that contract using existing field types only (`INVARIANTS`/`RATIONALE`) if a gap is found, never by inventing new fields.
- [x] 3.3 Confirm `openspec validate logging --json` reports `valid: true` and `uv run pytest -m unit` for the logging-discipline guard tests still passes.

## 4. Slim package-facades spec (package-facades)

- [x] 4.1 Drop the "Old deep paths are gone" scenario from the Public API stability requirement in `openspec/specs/package-facades/spec.md` — the transition artifact is no longer informative.
- [x] 4.2 Remove the historical "BREAKING change to the facade dict shape" parenthetical from the Yascheduler facade public contract requirement body; keep the structural description of the `node` key as the current shape.
- [x] 4.3 Confirm `openspec validate package-facades --json` reports `valid: true` and `uv run pytest -m unit` for facade tests still passes.

## 5. Slim query-path integration spec (test-db-integration)

- [x] 5.1 Drop the "Test asserts status against `domain.TaskStatus`" scenario from the Yascheduler query path integration requirement in `openspec/specs/test-db-integration/spec.md` — the "Status assertions SHALL use `yascheduler.domain.TaskStatus`" line in the requirement body already covers the contract.
- [x] 5.2 Confirm `openspec validate test-db-integration --json` reports `valid: true` and the integration test file does not assert on the dropped scenario name.

## 6. Tighten yainit service-install scenarios (cli)

- [x] 6.1 In `openspec/specs/cli/spec.md`, rename and tighten the "yainit detects systemd via `/run/systemd/system`" and "yainit detects non-systemd host" scenarios under the CLI commands call use cases via DI requirement so each asserts which file is written on which host condition, without restating the exact probe path string the code branches on.
- [x] 6.2 Confirm `openspec validate cli --json` reports `valid: true` and `uv run pytest -m unit` for the yainit / init tests still passes.
