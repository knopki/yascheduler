## proposal+design+specs+tasks Round 1 — 2026-07-01

Reviewer: @k-reviewer-fast (batch review of all four artifact types at once against `explore-brief.md`).

### Verdict
APPROVE — no 🔴 blocking issues. Batch ready to freeze.

### 🟡 Addressed this round
- **Spec/design tension on VM-count assertion** — design Risks stated "the test does NOT assert exact VM count ... a 2nd VM is non-fatal", but `specs/e2e-testing/spec.md` step 7 + the "both jobs run to DONE" scenario required both tasks' `allocated_ip` to equal the single node's IP — which would FAIL if the idle-deallocate race provisioned a 2nd VM. Fixed by softening the spec assertion: each `allocated_ip` must be a `cloud=="hetzner"` node IP observed during the test; the test SHALL NOT require both IPs to be identical. `tasks.md` 5.3 updated to match ("Outputs + cloud-node assignment"). Now spec ↔ design ↔ tasks are consistent.

### 🟡 Noted, no action (non-blocking)
- Delta specs omit the `# Title` / `## Purpose` heading that main specs carry — this is the established OpenSpec delta convention; consistent across all three deltas.
- `_cloud_env_or_skip()` and the `hetzner_config` fixture both read the same env vars — harmless (fixture resolves lazily after the gate check passes); already documented across tasks 2.2 / 3.1.

### 🔴 Outstanding
None.

## implementation Round 1 — 2026-07-01

Reviewers: 3× parallel @k-reviewer-fast (1) grace-lite-reviewer skill, 2) openspec-verify-change skill, 3) bug hunt).

### Verdict
APPROVE WITH NOTES — all spec requirements satisfied; 1 actionable GRACE-lite fix applied; all other findings are accepted design trade-offs or out-of-scope pre-existing issues.

### 🔴 Fixed this round
- **GRACE-lite: missing CHANGE_SUMMARY/VERSION bump on `tests/unit/test_cloud_provisioner_impl.py`** (edited to add the `cloud_package_upgrade` propagation test + update the existing test). Bumped VERSION 2.6.0→2.7.0 and added a `LAST_CHANGE: v2.7.0` entry. (grace-lite-reviewer MINOR 1.)

### 🟡 Noted, no action (accepted design trade-offs / out of scope)
- **VM-leak window when test fails before `_poll_for_hetzner_node` records an IP** (bug-hunt RISK 1). `_cleanup_observed` early-returns on empty `observed_ips`. This is the designed contract per design D5: "the loud-fail contract covers every in-process failure [for observed VMs]"; "`max_nodes=1` bounds the worst case to one VM"; "a hard process kill is an operational concern outside this change's scope". Scenario 10 explicitly scopes cleanup to `observed_ips`; a name-prefix sweep is forbidden (D5). Daemon-first ordering is mandated by spec scenario step 1. No change.
- **Pre-existing `find_srv` IP comparison** (`yascheduler/infra/cloud/providers/hetzner.py:156`) — compares `public_net.ipv4.ip` against a `str` without `str()` coercion; could fail if a future hcloud SDK returns an `IPv4Address` (bug-hunt RISK 2). NOT introduced by this change; explicitly out of scope per proposal Non-Goals ("Any change to the Hetzner provider code"). The new test depends on `find_srv`; task 8.1 manual smoke will surface it if real, and a follow-up change would fix it. hcloud is not installed in CI so this can't block collection.
- **`cloud_package_upgrade=None` silently passes `__post_init__`** (bug-hunt NIT 1). Consistent with the existing `if value is None: continue` pattern (e.g. `webhook_url`); spec explicitly states "No `__post_init__` validation needed (any bool accepted)". Parser uses `getboolean` (returns bool). No change.
- **`_submit_two_jobs` CWD not restored on raise** (bug-hunt NIT 2). Matches the established `test_full_cycle.py::_submit_four_jobs` pattern exactly; finally doesn't depend on CWD. No change.
- **Function/module soft-size limits on `tests/e2e/test_hetzner_live.py`** (grace-lite-reviewer MINOR 2/3). `grace_check.py` exits 0 (soft limits only); block anchors preserve navigability. Acceptable for an e2e test.

### ✅ Confirmed
- openspec-verify: all 3 delta specs (cloud-provisioner, config-value-objects, e2e-testing) — every requirement/scenario SATISFIED with evidence.
- grace-lite-reviewer: all M-IDs valid (used `M-CLOUD-PROVIDER-HETZNER`/`M-DI` instead of the non-existent `M-CLOUD-HETZNER`/`M-ENTRYPOINTS-DI` from the task text); graph not spuriously modified; test module kept out of graph; all contracts/blocks paired.
- Verification suite green: `ruff check` + `ruff format --check` + `lint-imports` + `zuban check` + `grace_check.py` (0 errors) + `openspec validate --all` (33/33) + `pytest -m unit` (732 passed) + `pytest tests/e2e -q` (4 passed, 1 skipped = new test, env unset, no API call).

### 🔴 Outstanding
None. Task 8.1 (live manual smoke against a real Hetzner project) — **DONE**, see below.

## live smoke Round 1 — 2026-07-01

Operator-assisted live run against a real Hetzner Cloud project (`YASCHEDULER_TEST_HETZNER=1` + real token). Goal: actually execute `test_hetzner_live` (prior "verification" was only skip-behaviour + statics; the test body had never run).

### Verdict
PASS — `1 passed in 101.43s`. One `cx23` VM created in `hel1`, both jobs reached DONE with matching outputs, idle-deallocate removed the row, `find_srv` confirmed deletion, project left at 0 servers. 5 SSH keys accumulated (documented acceptable cost).

### 🔴 Fixed this round (test-logic bugs found only by running live)
- **Root cause it couldn't run at all: `hcloud` extra not installed.** `hetzner = ["hcloud~=2.0"]` is optional; the env gate checks env vars but the SDK was absent → `hetzner_create_node` raised `ImportError` before any API call → no node ever appeared → autoscale timed out silently. Fix: `uv sync --extra hetzner` (operator setup; the collection-without-SDK guarantee is unchanged — collection still passes without hcloud). Note: gate stays env-only per design D1; hcloud install is an implicit precondition of a real run, like the token.
- **`_poll_for_hetzner_node` matched the tmp-node.** `_select_and_insert_tmp` inserts a tmp node with `cloud="hetzner"`/`enabled=False` and a placeholder IP; the poll filtered only `cloud=="hetzner"` and would return the placeholder. Fix: require `n.enabled` — the real provisioned node is committed `enabled=True` in `_persist_node_with_cleanup` (which atomically removes the tmp row in the same commit).
- **`CLOUD_DELETE` asserted too early.** The single `_assert_cloud_logs` ran right after both tasks DONE, but `[deallocate_node][CLOUD_DELETE]` is emitted by the idle-deallocate loop (step 9, ~`idle_tolerance` after completion), so it was absent at step 8 → `AssertionError: no [CLOUD_DELETE] record ... msgs=[]`. Fix: split into `_assert_cloud_done_log` (after completion — CLOUD_DONE is emitted at provision time) and `_assert_cloud_delete_log` (after `_poll_node_gone`, once deallocate has fired).

### 🟡 Noted, no action
- **Timeouts were 600s** (copied verbatim from the spec's "at least 600 seconds"). Observed cold-start provision is ~83s; total run 101s. Reduced to autoscale=120 / completion=60 / dealloc=60 / vm_delete=30 (≈1.4× the observed values). The spec's "at least 600s" is a safe upper bound but absurdly loose for a <2-min test.
- **Bug-hunter's `find_srv` IPv4Address claim was wrong.** Verified against hcloud 2.20.0: `Server.public_net.ipv4.ip` is a `str` (per the `IPv4Address` domain class docstring `:param ip: str`); `find_srv`'s `== host` comparison works. No fix needed (and out of scope per proposal Non-Goals anyway).
- **No cleanup/DELETED logs visible in the first (failing) run**, yet the project ended at 0 servers — the daemon's own idle-deallocate loop deleted the VM before/independently of the `finally`. The `finally`'s observed-IP cleanup is the designed safety net for in-process failures; in the success path the daemon self-cleans.

### ✅ Confirmed live
- Daemon autoscaled exactly one `cloud==hetzner` node (`77.42.27.52`).
- Both tasks DONE; outputs saved to per-job CWDs; `1.input.out` matched payloads.
- Idle-deallocate fired; node row removed; `find_srv` → None; 0 servers left.
- `[CLOUD_DONE]` and `[CLOUD_DELETE]` markers captured by `log_records` (both on `yascheduler.application.*` loggers).

### 🔴 Outstanding
None.
