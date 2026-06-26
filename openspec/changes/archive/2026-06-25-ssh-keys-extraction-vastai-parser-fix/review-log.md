# Review Log: ssh-keys-extraction-vastai-parser-fix

## proposal Round 1 — 2026-06-25

### 🔴 Fixed
*(none — review-only agent)*

### 🟡 Addressed

**1. `cloud-providers` spec modification is scope drift**
- **Problem**: The proposal claims `cloud-providers` spec gains a VastAI-parser scenario. But `cloud-providers/spec.md` is about *provider SDK relocation* — moving provider code to `infra/cloud/providers/`. Adding a parser-recognition requirement to it conflates concerns. The VastAI round-trip assertion fits naturally in `testing-unit/spec.md` (which already has "Cloud config parsing (Hetzner, UpCloud, Azure)" under "Config parsing and validation"). The `cloud-providers` spec should remain focused on SDK relocation.
- **Fix**: Drop the `cloud-providers` spec modification from the proposal. The VastAI parser requirement lives entirely in `testing-unit` spec.

**2. Test mock files not acknowledged**
- **Problem**: 6 test files mock `config.local.get_private_keys` on MagicMock objects:
  - `tests/unit/test_cli_check_status.py:95`
  - `tests/unit/test_cli_show_nodes.py:69`
  - `tests/unit/test_cloud_provisioner_impl.py:172`
  - `tests/unit/test_cli_submit.py:69`
  - `tests/unit/test_cli_behavioral.py:64`
  - `tests/unit/test_cli_manage_node.py:60`

  They are all safe (MagicMock accepts arbitrary attribute assignment), but the proposal's Impact > Tests section should mention they were reviewed and confirmed unaffected.

**3. Plan doc call-site drift**
- **Problem**: `docs/config-layer-split-plan.md` §4 lists `cloud/manager._get_ssh_key` as a call site, but the actual call is in `cloud/manager._connect_to_vm` (line 386). `_get_ssh_key` (line 256) uses `keys_dir` directly, not `get_private_keys()`. The proposal correctly names the file, so this is not a proposal defect — but the plan doc should be corrected when touched next.

### 🔴 Outstanding

**1. Missing 4th call site: `entrypoints/cli/check_status.py`**
- **Location**: proposal.md lines 8–9 ("Update the three call sites…")
- **Problem**: The proposal claims 3 call sites but there are **4 production call sites** for `get_private_keys()`:
  1. `application/orchestrator.py:222` — `self._config.local.get_private_keys`
  2. `infra/cloud/manager.py:386` — `self.local_config.get_private_keys`
  3. `entrypoints/cli/manage_node.py:267` — `config.local.get_private_keys()`
  4. **`entrypoints/cli/check_status.py:319`** — `config.local.get_private_keys()` ← MISSING

  `check_status.py` connects to a remote machine in `_display_remote_output` and passes `client_keys=config.local.get_private_keys()` to `gateway.connect()`. If not updated to `list_private_keys(config.local.keys_dir)`, the extraction will leave a broken import in production code.
- **Fix**: Add `entrypoints/cli/check_status.py` to the call-sites list in lines 8–9 and to the Impact > Code file list in line 23.

**2. `check_status.py` also missing from umbrella plan doc**
- **Location**: `docs/config-layer-split-plan.md` §4 lines 170–171
- **Problem**: The umbrella plan also lists only 3 call sites, missing `check_status.py`. When the proposal is corrected, the plan doc should be corrected in sync.
- **Fix** (for the author, not in this proposal.md): Update P1 section of plan doc to include `check_status.py`.

---

**Summary**: 1 outstanding issue (missing call site), 3 addressed suggestions. After fixing issue #1 (adding `check_status.py` to the call-sites list and Impact file list), this batch is ready to freeze.

**Recommendation**: REQUEST CHANGES — the missing call site in `check_status.py` must be acknowledged before freezing, otherwise the implementation scope is incomplete.

## proposal Round 2 — 2026-06-25

### 🔴 Fixed

1. **Missing 4th call site `check_status.py`** — now listed in both What Changes (line 8: "four call sites" with `check_status.py`) and Impact > Code (line 23: `yascheduler/entrypoints/cli/check_status.py`). ✅

2. **Plan doc call-site drift** — `docs/config-layer-split-plan.md` §4 P1 (line 170–172) now lists 4 call sites and uses `_connect_to_vm` (not `_get_ssh_key`). ✅

### 🟡 Addressed

1. **`cloud-providers` spec modification removed** — Modified Capabilities (lines 18–19) lists only `testing-unit`; no mention of `cloud-providers`. ✅

2. **Test mock files acknowledged** — Impact > Tests (line 27) includes the full paragraph listing 6 test files with the "reviewed and confirmed unaffected" statement. ✅

### 🔴 Outstanding

None.

### Verification summary

| Check | Result |
|---|---|
| `check_status.py` in call-site list | ✅ line 8 |
| `check_status.py` in Impact > Code | ✅ line 23 |
| Modified Capabilities = `testing-unit` only | ✅ lines 18–19 |
| Test-mock acknowledgment in Impact > Tests | ✅ line 27 |
| No P2/P3/P4 scope creep | ✅ scope is exactly P1 items |
| Honors `docs/config-layer-split-plan.md` §4 P1 | ✅ all 4 P1 items covered |

Batch proposal passes — ready to freeze.

## tasks Round 1 — 2026-06-25

### 🔴 Fixed
*(none)*

### 🟡 Addressed

**1. Task 4.4 outcome depends on `list_private_keys` avoiding `Path(keys_dir)`**
- **Location**: tasks.md:30
- **Problem**: The task claims 6 tests "still pass" because they use duck-typed MagicMock. Verified that `test_cli_manage_node.py::test_add_happy_path` exercises `_add_node` which after migration calls `list_private_keys(config.local.keys_dir)`. The mock config does not set `keys_dir`, so it's an auto-created MagicMock. `iter(MagicMock())` returns `[]` — so `list_private_keys` works **only if** it uses `keys_dir.iterdir()` directly (not `Path(keys_dir).iterdir()`, which would raise `TypeError` on a MagicMock). `test_cloud_provisioner_impl.py`'s mock has `iterdir.return_value = []` which also requires `.iterdir()` call style.
- **Fix**: Task 1.1 should specify `keys_dir.iterdir()` not `Path(keys_dir).iterdir()` since the argument is already a `Path`. The "Verify" instruction in 4.4 is still correct as a safeguard — the implementer will catch this at test time.

**2. Two `MagicMock(spec=ConfigLocal)` mocks mentioned in design risks but not in tasks**
- **Location**: tasks.md:30 (task 4.4)
- **Problem**: The design.md Risk section (line 65) flags 2 spec'd mocks (`test_di.py:59`, `test_application_orchestrator.py:82`). Task 4.4 covers the 6 duck-typed mocks but doesn't mention these 2. Verified they never access `get_private_keys` so they're safe, and task 5.1 (full unit test run) catches any breakage. Not a blocking issue, but the design's explicit risk call-out should be traceable to a task mention.
- **Fix**: Add a parenthetical note to task 4.4 like "(plus 2 `MagicMock(spec=ConfigLocal)` in `test_di.py` / `test_application_orchestrator.py` — confirmed they never access `get_private_keys`; covered by 5.1)".

### 🔴 Outstanding

None.

### Summary
- All spec scenarios → at least one task ✅
- All design decisions → at least one task ✅
- All risk mitigations → at least one task ✅
- Task dependency ordering correct ✅
- GRACE-lite module-level artifacts covered ✅
- No missing tasks ✅
- Two minor clarifications above 🟡
