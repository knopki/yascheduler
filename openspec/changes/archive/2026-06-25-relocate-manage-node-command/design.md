## Context

`yascheduler/infra/cli/manage_node.py` (174 lines) implements the `yasetnode`
CLI command — the operator-side entry point for adding, soft-removing, and
hard-removing nodes from the scheduler. Three archived predecessors
(`relocate-init-command`, `relocate-show-nodes-command`,
`relocate-submit-command`) established a repeatable relocation pattern from
`infra/cli/` into `yascheduler/entrypoints/cli/`. `manage_node` is the 4th
resident; `check_status` and `daemonize` remain for follow-up changes.

The current implementation carries latent bugs (silent IPv6 data corruption,
`type=bool nargs="?"` argparse footgun, missing exit-code contract, gateway
resource leak, pre-commit prints) documented in `proposal.md`. The move is the
moment to bring it to the modern standard set by `init`/`show_nodes`/`submit`
(`prog`, `argv`, `0`/`1`/`2` exit codes, fresh GRACE-lite markup) while
preserving the documented public interface exactly.

**Stakeholders:** operators using `yasetnode` interactively or in scripts;
the AiiDA scheduler plugin (unaffected — `yasetnode` has no machine
consumer); maintainers of the `infra/cli/` and `entrypoints/cli/` packages.

**Constraints:**
- Public interface stability (AGENTS.md): CLI command name, documented host
  syntax forms, INI config format. The compact host syntax
  `[user@]IP[:port][~ncpus]` is preserved; only its parsing is hardened.
- Layer direction (`import-linter`): `entrypoints → infra` only; no reverse
  re-export shim.
- Python `>=3.9` (`pyproject.toml`); stdlib-only (no new dependencies).
- GRACE-lite markup required on the new governed file; `grace_check.py` must
  exit 0.
- OpenSpec: `openspec validate --all --json` must pass after spec deltas land.

## Goals / Non-Goals

**Goals:**
- Move `manage_node.py` from `infra/cli/` to `entrypoints/cli/` following the
  established relocation pattern (real move, no shim).
- Fix the IPv6 silent-corruption bug by introducing a custom argparse type
  with mandatory bracketed IPv6.
- Adopt the modern CLI contract: `prog="yasetnode"`, `argv` parameter,
  `0`/`1`/`2` exit codes, stdout/stderr channel discipline.
- Fix the gateway resource leak with `try/finally`.
- Replace the buggy `type=bool nargs="?"` flag pattern with `store_true`.
- Make `_add_node` unit-testable via parameter injection (no `patch.object`
  on the gateway class).
- Update knowledge graph, specs, and tests to match.

**Non-Goals:**
- Extract an `application/manage_node.py` use case (YAGNI — no second
  consumer; the daemon-side node lifecycle is owned by the orchestrator).
- Migrate `check_status` or `daemonize` (separate follow-up changes).
- Decouple the username default from `[remote] user` (config-driven default
  preserved).
- Add a `--re-enable` flag (status quo: remove + add cycle).
- Add multi-host add (one host positional; feature, out of scope).
- Add output-mode flags (`--json`/`--table`); `yasetnode` is a write/mutate
  command, not a query command. The `--json` convention from `show_nodes`
  applies to query-oriented commands only.

## Decisions

### D1 — Real move, no compat shim

**Choice:** Delete `infra/cli/manage_node.py`; do not add a re-export shim.

**Rationale:** Any `infra → entrypoints` re-export inverts the layer direction
enforced by `import-linter`. Same call as `relocate-init-command` D1,
`relocate-show-nodes-command` D1, `relocate-submit-command` D1.

**Alternatives rejected:**
- *Compat shim re-exporting `manage_node` from `infra/cli/__init__.py`* —
  layer inversion; the `import-linter` `layers` contract forbids it. Also
  leaves a stale facade entry that future readers must reason about.

### D2 — Custom argparse type `_parse_host_spec` returning `HostSpec`

**Choice:** A single positional `host` argument with
`type=_parse_host_spec`, where `_parse_host_spec(s: str) -> HostSpec` parses
the grammar `[user@]host[:port][~ncpus]` and returns a frozen dataclass.
Malformed input raises `argparse.ArgumentTypeError` → exit 2.

**`HostSpec` shape (frozen dataclass):**

| field      | type            | source                                       |
| ---------- | --------------- | -------------------------------------------- |
| `host`     | `str`           | parsed, non-empty                            |
| `username` | `str \| None`   | `None` if no `user@` (resolved later from config) |
| `port`     | `int`           | parsed or `22` (parser-applied default); validated `1..65535` |
| `ncpus`    | `int \| None`   | `None` if absent OR if `~0` (unlimited); positive int as-is; `>= 0` enforced |

**Rationale:** The host grammar is *syntactic shape*, not content. Mirrors the
argparse-layer / body-layer validation split established by `submit`'s
`type=_existing_path`: argparse owns argument *shape* (the host string
parses to a valid spec); the body owns *content* / orchestration
(already-in-DB, dispatch to add/remove). Promoting parsing to a custom type
also makes `_parse_host_spec` a pure, directly-unit-testable function (no
`patch("sys.argv", ...)` needed for grammar tests).

**Alternatives rejected:**
- *Keep inline parsing in the body, wrap whole function in try/except* —
  leaves validation mixed with orchestration; `int("abc")` for port/ncpus
  surfaces as a runtime exit 1 instead of an argparse-shaped exit 2;
  harder to unit-test the grammar in isolation.
- *Replace the compact syntax with structured flags `--user/--port/--ncpus`* —
  breaking change to the documented public host syntax; rejected by the
  compatibility constraint.

### D3 — IPv6 mandatory in brackets

**Choice:** The `host` portion of the grammar is either an IPv4 literal or a
bracketed IPv6 literal `[...]`. IPv6 without brackets is rejected
(`ArgumentTypeError` → exit 2).

**Rationale:** IPv6 contains `:`, which collides with the `:port` suffix.
`::1:22` is unparseable. Brackets (URL-style, RFC 3986) disambiguate:
`[::1]` or `[::1]:22`. The current code silently corrupts unbracketed IPv6
(`manage_node ::1` → `host="::"`, `port=1` — wrong host written to DB).

**Alternatives rejected:**
- *IPv6 without brackets* — fundamentally ambiguous against `:port`; no
  deterministic grammar exists.
- *Allow optional brackets around IPv4 (e.g., `[10.0.0.1]`)* — adds parser
  complexity for no disambiguation benefit; IPv4 has no `:` collision.
  Brackets remain an IPv6-only convenience, matching URL convention.

### D4 — Parser-applied defaults; username config-resolved

**Choice:** The parser applies `port=22` and `ncpus=None` defaults directly
in `HostSpec`. `username` is left `None` by the parser; `manage_node`
resolves it from `config.remote.username` (falling back only when the user
did not write `user@`).

**Rationale:** `port=22` is a protocol constant (SSH default) and
`ncpus=None` is a grammar-level sentinel — both are config-independent, so
the parser can own them. `username`'s default is config-driven
(`[remote] user`), and the parser is a pure function with no config access;
resolving it in `manage_node` preserves the config coupling that the current
code has (`username = config.remote.username`). Hardcoding `"root"` in the
parser would break deployments with `[remote] user = xyz`.

**Alternatives rejected:**
- *Parser hardcodes `username="root"`* — silent behavior change for any
  deployment with a non-root `[remote] user`; the config override would be
  ignored on the default path.
- *Parser resolves username by accepting a `Config` argument* — breaks the
  argparse-type contract (`type=` callables take one string arg) and the
  purity of `_parse_host_spec`.

### D5 — `store_true` replaces `type=bool nargs="?"`

**Choice:** `--skip-setup`, `--remove-soft`, `--remove-hard` all use
`action="store_true"`.

**Rationale:** The current `nargs="?", type=bool, const=True` pattern is a
classic argparse footgun: `bool("false") is True`, so `--skip-setup false`
*activates* skip-setup. `store_true` is the idiomatic flag form and removes
the value-taking variant entirely.

**Behavior change:** `--skip-setup VALUE` (undocumented) previously activated
the flag for any non-empty value; it now exits `2` (argparse treats `VALUE`
as an unknown extra). Marked **BREAKING** in `proposal.md` (a welcome fix on
a buggy/undocumented path).

### D5a — `prog="yasetnode"` and updated description

**Choice:** `ArgumentParser(prog="yasetnode", description="Add or remove
nodes from the yascheduler daemon")`.

**Rationale:** `prog` makes `--help`/error screens show the command name
instead of the resolved binary path (mirrors `init`/`show_nodes`/`submit`).
The description replaces the current misleading `"Add nodes to yascheduler
daemon"` text, which lied about half of what the command does (it also
removes nodes).

### D6 — `--remove-soft` and `--remove-hard` in a mutually exclusive group

**Choice:** `parser.add_mutually_exclusive_group()` containing the two
remove flags. Passing both exits `2`.

**Rationale:** The two actions are semantically exclusive (delayed disable
vs. immediate delete + task-done cascade). Today's code silently picks
hard via `if/elif`, hiding the conflict from the operator. argparse's mutex
group surfaces it as a usage error.

### D7 — `--skip-setup × remove` checked at body level via `parser.error`

**Choice:** After `parse_args`, if
`args.skip_setup and (args.remove_soft or args.remove_hard)`, call
`parser.error("--skip-setup cannot be combined with --remove-soft/--remove-hard")`
→ exit 2.

**Rationale:** `--skip-setup` is only meaningful on the add path. Today it
is silently ignored on remove. argparse's `mutually_exclusive_group` cannot
express "skip-setup is incompatible with either of {remove-soft, remove-hard}
but may be absent alongside both" — that's not a 1-of-N constraint. A
body-level `parser.error()` call produces the correct exit-2 argparse-shaped
error without contorting the parser declaration.

**Alternatives rejected:**
- *Three-way mutex over {skip-setup, remove-soft, remove-hard}* — would
  forbid plain add (no flags), which is the default path. Wrong semantics.
- *Silently ignore `--skip-setup` on remove (status quo)* — hides an
  operator mistake; rejected.

### D8 — Exit-code contract `0`/`1`/`2`; already-in-DB / NOT-in-DB → exit 1

**Choice:**
- `0` on success.
- `1` on runtime failure: host already in DB (on add), host NOT in DB (on
  remove), SSH/DB/config failure, any uncaught exception.
- `2` on argparse error (shape/grammar/flag conflict).

**Rationale for exit 1 on already-in-DB / NOT-in-DB:** mirrors how `submit`
treats "ENGINE missing" as exit 1 — the requested action did not happen, so
scripts should detect it. The current `return False` propagates through
`@to_sync` and the process exits `0`, masking the no-op from any caller that
checks exit codes.

**Behavior change:** callers relying on exit `0` for these paths now see
exit `1`. Marked **BREAKING** in `proposal.md`.

**Alternatives rejected:**
- *Exit 0 with an informational message (idempotent interpretation)* —
  inconsistent with `submit`'s precedent; masks operator error from scripts.

### D9 — Success messages verbatim, in stdout, AFTER commit

**Choice:** The seven success messages documented in `proposal.md` are
preserved word-for-word, printed to stdout, and emitted **after**
`await uow.commit()` succeeds. Each success message is co-located with the
path that produces it: it is printed inside the owning helper, immediately
after that helper's own `await uow.commit()` (see D18).

**Rationale:** The verbatim text preserves any operator script that grep for
these strings (verified: no in-repo consumer; external operators may). The
ordering change fixes a latent inconsistency: today, `_remove_node_hard`
prints per-task "marked done" messages *before* commit, so a commit failure
rolls back the DB while the user has already seen success text. Moving
prints after commit makes the observable output match the committed state.

The one exception is the `Setup host...` progress announcement, which is a
*phase indicator* printed before `gateway.setup_node(...)` runs (it tells the
operator "setup is about to start"), NOT a success confirmation. It is the only
message printed before commit; all six *confirmation* messages print after
commit. This split mirrors the spec delta's table label `add, before setup`
(vs `add, after commit`), which already distinguishes the two phases.

**Alternatives rejected:**
- *Move prints before commit (status quo)* — observable state diverges from
  committed state on commit failure.
- *Batch all per-task prints into a single summary line* — changes the
  verbatim text; rejected.
- *Have helpers return message payloads and print them in `manage_node`
  after a single commit at the `async with` boundary* — centralizes the
  commit (cleaner UoW idiom) but threads verbatim strings through return
  values, splitting "what to announce" from "what happened" across two
  functions. Rejected in favor of D18 (per-helper UoW), which keeps the
  commit-and-announce pair local to each path without the plumbing.

### D10 — Uniform `Error: <message>` via raise + top-level catch

**Choice:** Failure paths (already-in-DB, NOT-in-DB, SSH/DB failures,
uncaught exceptions) raise `ValueError` (or let the original exception
propagate); the top-level `manage_node` body wraps the orchestration in
`try/except Exception as e: print(f"Error: {e}", file=sys.stderr);
sys.exit(1)`.

**Rationale:** Uniform error format matches `submit`/`show_nodes`/`init`.
Modeling already-in-DB and NOT-in-DB as raised `ValueError`s (rather than
explicit early-return branches with bespoke messages) keeps a single error
formatting path.

**Behavior change:** failure messages move from stdout to stderr. Marked
**BREAKING** in `proposal.md` (no in-repo consumer; no documented contract).

### D11 — `try/finally` around gateway connect/disconnect

**Choice:** In `_add_node`, the sequence `gateway.connect(...)` → optional
`gateway.setup_node(...)` → `uow.nodes.add(...)` is wrapped in `try/finally`
with `gateway.disconnect(host)` in the `finally` block. The disconnect runs
on both success and failure paths. Under D18, the `uow` used inside `_add_node`
is the helper's own UoW (opened and committed inside the helper), not the
validation UoW; the `try/finally` covers `connect → setup → nodes.add → commit`.

**Rationale:** Fixes a resource leak — today, if `setup_node` or
`nodes.add` raises after `connect` succeeds, `disconnect` is never called
and the SSH connection hangs until timeout.

### D12 — Gateway constructed at top of `manage_node`, passed to `_add_node`

**Choice:** `SSHMachineGateway()` is constructed once at the top of
`manage_node` and passed as a parameter to `_add_node(deps, gateway, spec,
config, skip_setup)`. The gateway is NOT constructed inside `_add_node`, and
NOT tied to any UoW; it is the long-lived SSH handle reused across the single
add invocation. Under D18, `_add_node` opens its own UoW from `deps` and owns
the commit; the gateway is passed in only so it can be mocked for tests.

**Rationale:** Symmetric with how `deps` is obtained at the top. Makes
`_add_node` unit-testable via direct mock injection (no
`patch.object(manage_node_mod, "SSHMachineGateway", ...)` needed). Removes
the only remaining constructor call hidden inside a helper.

**Alternatives rejected:**
- *Keep `SSHMachineGateway()` inside `_add_node` (status quo)* — keeps the
  class-level patch surface for tests; rejected because the existing test
  is being rewritten anyway and the new design is strictly cleaner.

### D13 — Helpers return `None`; exit codes replace bool signaling

**Choice:** `_remove_node_hard`, `_remove_node_soft`, `_add_node` all return
`None`. The `manage_node` body uses exit codes / exceptions for signaling.

**Rationale:** Today's mixed `bool | None` return type is odd — the
`@to_sync` wrapper propagates the return value but no caller uses it (the
console_script discards it). Exit codes are the right signaling layer for a
CLI.

### D14 — Logging setup adopted from `submit`

**Choice:** At the top of `manage_node`'s body, before the orchestration:
`logging.captureWarnings(True)`; `log = logging.getLogger()`;
`log.setLevel(logging.WARN)`.

**Rationale:** Config parsing emits warnings via `warn_unknown_fields`
(`config/utils.py`). Without `captureWarnings` and a WARN level, those
warnings are invisible to the operator. `submit` established this pattern;
`manage_node` adopts it for consistency.

### D15 — `~0` and absent `~ncpus` both map to `None` (unlimited)

**Choice:** `_parse_host_spec` returns `HostSpec.ncpus = None` both when
`~ncpus` is absent and when the user writes `~0`. Downstream, the `Node`
record is constructed with `ncpus=0` (the existing convention — `0` means
"MAX"/unlimited, rendered as `MAX` in `yanodes`).

**Rationale:** `0` and "unspecified" are semantically identical in the
current code (`ncpus or 0` collapses both to `0`). Representing both as
`None` in `HostSpec` makes the "unlimited" intent explicit at the dataclass
layer, while preserving the DB-level `0` encoding exactly.

### D16 — Drop stale `# FIXME`

**Choice:** Do not carry `# FIXME: split adapter and application layer` to
the new file.

**Rationale:** Same call as `relocate-submit-command` D13 — the FIXME's
framing ("adapter vs application layer") is stale at the new home
(`entrypoints/` is the driving-adapter layer, not the driven-adapter layer
the FIXME was written about). The in-module function split resolves the
logic-vs-IO separation at the appropriate granularity.

### D17 — Fresh GRACE-lite markup at v1.0.0

**Choice:** New `MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`, function
contracts (`START_CONTRACT:`/`END_CONTRACT:`), and block anchors
(`START_BLOCK_`/`END_BLOCK_`) at the new path, versioned `1.0.0`.

**Rationale:** Real reimplementation, not a rename. Fresh markup matches
what `init`, `show_nodes`, and `submit` received at their moves.

### D18 — Per-helper UoW; validation UoW read-only and closed before dispatch

**Choice:** `manage_node` opens a short, read-only UoW for the
`already_there` validation check (`uow.nodes.get(spec.host)`), closes it
(without commit — nothing was mutated), then dispatches to exactly one
helper. Each helper (`_remove_node_hard`, `_remove_node_soft`, `_add_node`)
opens its OWN UoW via `deps.uow_factory()`, performs its mutations, calls
`await uow.commit()`, and prints its success messages — all inside that
single helper-owned UoW. Helper signatures take `deps` (the `CLIDeps`
factory holder) and `spec`, not an already-open `uow`.

**Rationale:** A commit scattered across helpers inside one shared `async
with` block is a latent double-commit bug: a future maintainer who adds
`uow.commit()` at the end of the `async with` block (the natural UoW-idiom
location) or refactors the `if/elif/else` dispatch into a loop/dispatch-table
silently double-commits. Giving each helper its own UoW makes the
transactional boundary local and unambiguous: each helper owns exactly one
open-commit-close cycle, and there is no outer `uow` for a stray commit to
land on. This also keeps the commit and the post-commit success prints
co-located (D9) without threading message payloads back to `manage_node`.

**Accepted trade-off — TOCTOU window:** between closing the validation UoW
and opening the dispatch UoW, the DB state can change. For a CLI invoked by a
single operator, concurrent mutation is unlikely and operations serialize
naturally. The failure mode is benign and non-corrupting: add-on-already-present
hits a unique constraint (or the helper's own `nodes.get` re-check) → exit 1;
remove-on-just-removed → no-op / not-found → exit 1. No silent data corruption.

**Alternatives rejected:**
- *Single shared UoW with one commit at the `async with` boundary (the
  textbook UoW idiom)* — cleanest transactionally (no TOCTOU), but forces the
  path-specific verbatim success messages out of the helpers (they would
  print before the single commit, violating D9) unless the helpers return
  message payloads for `manage_node` to print after commit. That plumbing
  splits "what to announce" from "what happened" across two functions and
  was rejected as over-engineering for a CLI with one operator.
- *Single shared UoW, helpers commit, no guard* — the original
  implementation direction; rejected because it is exactly the double-commit
  footgun D18 exists to eliminate.

## Risks / Trade-offs

| Risk | Mitigation |
| --- | --- |
| Operators relying on exit `0` for the already-in-DB / NOT-in-DB paths see scripts now report failure (exit `1`). | Documented as **BREAKING** in `proposal.md` with the new contract. The success path (the documented happy path for add and remove) is unchanged. Operators who relied on the no-op exit code can drop the call or check stderr. |
| Operators relying on `--skip-setup VALUE` form see exit `2`. | Documented as **BREAKING**. The form was undocumented and buggy (`--skip-setup false` activated it). The flag form `--skip-setup` (no value) is the documented usage and is preserved. |
| Operators relying on failure text in stdout see it move to stderr. | Documented as **BREAKING**. No in-repo consumer; no documented contract. The success messages (the documented operator-facing strings) are preserved verbatim in stdout. |
| IPv6-requiring deployments used unbracketed IPv6 and saw silent corruption; the new strict grammar rejects their old invocation. | The old behavior was a silent data-corruption bug, not a contract. The fix is documented; the bracketed form is the new documented syntax. |
| `_parse_host_spec` is too strict (rejects a hostname the operator expects to work). | The grammar accepts any non-empty `host` string after parsing — it validates *structure* (the `user@`, `:port`, `~ncpus` segmentation and IPv6 bracketing), not *reachability* or *DNS validity*. A hostname like `compute-node-7` passes. |
| `parser.error()` for the `--skip-setup × remove` combo runs after `parse_args`, slightly delaying the error vs a native argparse mutex. | Negligible — the error still surfaces before any side effect. The body-level check is the only way to express the constraint short of contorting the parser declaration. |
| `try/finally` disconnect on failure may mask the original exception if `disconnect` itself raises. | Acceptable: `disconnect` failures are logged by the gateway; the original exception is the one we want to surface. If masking becomes an issue, a later change can chain exceptions. Out of scope here. |
| The knowledge-graph update misses a `<depends>` reference, leaving a stale `M-ID` pointer. | `python3 scripts/grace_check.py` validates graph integrity (hard-gates `<depends>` refs and `CrossLink` endpoints); the tasks checklist enumerates the exact nodes to touch. |
| Reviewer/implementation drift on the verbatim success-message list. | The list is enumerated in both `proposal.md` and the spec delta (`cli-commands/spec.md`); `design.md` references both rather than re-listing. |
| Per-helper UoW (D18) opens a TOCTOU window between the validation read and the dispatch mutation. | Accepted. For a single-operator CLI, concurrent mutation is unlikely and operations serialize. Failure modes are benign and non-corrupting (unique-constraint / not-found → exit 1); no silent data corruption. See D18 for the full rationale. |

## Migration Plan

**Deployment:** single PR; no service restart required (the `yasetnode`
console_script target is updated in `pyproject.toml`; the installed entry
point resolves to the new path on `pip install -e .` or equivalent). The
daemon is unaffected.

**Order of operations within the change:**
1. Create `yascheduler/entrypoints/cli/manage_node.py` (fresh implementation,
   fresh markup).
2. Update `pyproject.toml` line 52.
3. Update `yascheduler/entrypoints/cli/__init__.py` (PURPOSE edit).
4. Delete `yascheduler/infra/cli/manage_node.py`.
5. Update `yascheduler/infra/cli/__init__.py` (drop re-export + `__all__` +
   `MODULE_MAP` line; bump VERSION + CHANGE_SUMMARY).
6. Update `docs/knowledge-graph.xml` (drop `<fn-manage_node>`; add
   `M-ENTRYPOINTS-CLI-MANAGE-NODE` + CrossLink).
7. Update `openspec/specs/cli-commands/spec.md` and
   `openspec/specs/package-facades/spec.md`.
8. Migrate tests: new `tests/unit/test_cli_manage_node.py`; drop
   `TestManageNode` from `tests/unit/test_cli_behavioral.py`; drop
   `test_manage_node_function_exists` from `tests/unit/test_cli_smoke.py`.
9. Run the verification ladder (`pytest -m unit`, `zuban check`, `ruff check`,
   `ruff format --check`, `lint-imports`, `grace_check.py`, `openspec
   validate --all --json`); smoke-check `yasetnode --help`.

**Rollback:** revert the PR. No DB migration, no config migration, no
persistent state. The old `infra/cli/manage_node.py` is restored from git.
The DB records created by either version are schema-compatible (no schema
change).

## Open Questions

None. All decisions closed during the explore phase and captured in
`explore-brief.md`. Specifically resolved:
- IPv6 brackets — mandatory (D3).
- `~0` semantics — maps to `None` (D15).
- Disabled node reactivation — remove + add cycle, status quo (Non-Goals).
- Gateway leak — `try/finally` (D11).
- Error message format — uniform `Error: …` via raise + catch (D10).
- Argparse description — updated to mention remove (in `proposal.md`).
- Validation ranges — port `1..65535`, ncpus `>= 0` (D2).
- Success messages — verbatim, after commit (D9), co-located per helper (D18).
- Username default — config-driven (D4).
- `--skip-setup × remove` combo — exit `2` via `parser.error` (D7).
- Logging setup — adopted from `submit` (D14).
- `test_cli_behavioral.py` — left in place, only `TestManageNode` dropped
  (Non-Goals).
- UoW ownership — per-helper UoW, validation read-only; accepted TOCTOU (D18).
