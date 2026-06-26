## 1. GRACE-lite: knowledge graph and contracts (top-down, before code)

- [x] 1.1 Update `docs/knowledge-graph.xml`: amend the `M-DI → M-SSH-GATEWAY`
       CrossLink relation to state that `make_daemon` constructs a single
       `SSHMachineGateway` shared by `CloudProvisionerImpl.machine_gateway`
       and `Orchestrator.gateway` on the `clouds is None` branch
- [x] 1.2 Update `START_CHANGE_SUMMARY` in
       `yascheduler/entrypoints/di.py` with a `LAST_CHANGE` entry describing
       the gateway-sharing refactor (keep the existing `PREVIOUS_CHANGE`)
- [x] 1.3 Update `START_CHANGE_SUMMARY` and the `stop` contract block in
       `yascheduler/infra/cloud/manager.py` to describe the new
       `disconnect_all`-delegating semantics (replace "No-op — compatibility
       hook")

## 2. Production code

- [x] 2.1 In `yascheduler/entrypoints/di.py` `make_daemon`: hoist
       `gateway = SSHMachineGateway(log=log)` above the `clouds is None`
       branch; on that branch pass `machine_gateway=gateway` to
       `CloudProvisionerImpl` and `gateway=gateway` to `Orchestrator`. Leave
       the `clouds is not None` branch unchanged (still creates a fresh
       `SSHMachineGateway` for the orchestrator)
- [x] 2.2 In `yascheduler/infra/cloud/manager.py` `CloudProvisionerImpl.stop`:
       replace the no-op body with
       `await self.machine_gateway.disconnect_all()`; keep the structured log
       line, retitled to reflect the new behavior

## 3. Unit tests

- [x] 3.1 In `tests/unit/test_di.py` `test_creates_dependencies_no_db`:
       tighten the existing `mock_gateway.assert_called()` to
       `mock_gateway.assert_called_once()` (locks the "exactly one
       SSHMachineGateway" spec scenario at line 213); additionally assert
       that the kwargs passed to `CloudProvisionerImpl` include
       `machine_gateway is mock_gw` (the same mock returned by the
       `SSHMachineGateway` patch), and that the same `mock_gw` is also passed
       as `gateway=` to the `Orchestrator` constructor
- [x] 3.2 In `tests/unit/test_di.py` `test_uses_provided_clouds`: add a
       `patch("yascheduler.entrypoints.di.SSHMachineGateway")` to avoid
       constructing a real `SSHMachineGateway` on the pre-built-clouds path
       (parity with the other tests); additionally assert
       `orch_kwargs["gateway"] is not custom_clouds.machine_gateway` (covers
       the "pre-built clouds path keeps its own gateway" spec scenario)
- [x] 3.3 In `tests/unit/test_cloud_provisioner_impl.py` `TestStop.test_stop`:
       rewrite to inject a mock gateway whose `disconnect_all` is an
       `AsyncMock`; assert that `await prov.stop()` awaits
       `gateway.disconnect_all` exactly once
- [x] 3.4 Add a focused test in `tests/unit/test_cloud_provisioner_impl.py`
       that calls `prov.stop()` twice and asserts both calls complete without
       raising and `disconnect_all` is awaited on the second call (idempotency
       guard for the spec scenario)

## 4. Validation

- [x] 4.1 `uv run pytest -m unit` — all green
- [x] 4.2 `uv run ruff check .` and `uv run ruff format --check .` — clean
- [x] 4.3 `uv run lint-imports` — clean
- [x] 4.4 `python3 scripts/grace_check.py` — exit 0
- [x] 4.5 `openspec validate --all --json` — passes (change artifacts + delta
       specs well-formed)
