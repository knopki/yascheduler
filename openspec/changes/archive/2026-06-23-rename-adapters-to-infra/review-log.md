## proposal Round 1 — 2026-06-23

### 🔴 Fixed
 - (none yet — this is the first review pass)

### 🟡 Addressed
 - Verified scope against `pyproject.toml`: the 6 `[project.scripts]` entry
   points (lines 49-54), the `layers` contract top-layer label (line 126),
   and the `[tool.setuptools.package-data]` key (line 140) are correctly
   identified and accurately described. AiiDA entrypoint key
   (`yascheduler = "yascheduler.aiida_plugin:YaScheduler"`, line 57) does
   NOT touch the adapters path — confirmed the "BREAKING (internal import
   paths only)" framing is accurate; no public API break is implied.
   Public API surface (CLI command names, `class Yascheduler`, INI format,
   DB schema, AiiDA entrypoint key) is genuinely preserved.
 - Verified the non-goal about preserving `CloudAdapter`
   (`yascheduler/adapters/cloud/adapters.py`), `RemoteMachineAdapter`
   (`yascheduler/adapters/ssh/platform/adapters.py`), and the two
   `adapters.py` file basenames is clearly stated (proposal lines 53-58)
   and internally consistent — the containing directory changes, the
   in-file class/module identifiers stay.
 - Confirmed `patch("yascheduler.adapters.…")` string targets in tests
   exist (2 hits in `tests/unit/test_ssh_gateway.py` lines 852, 876) and
   are captured by the proposal's scope (proposal line 47-49).
 - Confirmed `di.py` does import from `.adapters` (line 33) and
   `.adapters.cloud` (line 40); the proposal captures this code change.
 - Confirmed `docs/knowledge-graph.xml` has many
   `<path>yascheduler/adapters/...</path>` entries (M-ADAPTERS, M-CLOUD,
   M-PLATFORM-ADAPTERS, M-SSH, M-PERSISTENCE, M-NOTIFIER, etc.); the
   proposal's plan to rewrite `<path>` children while preserving M-IDs
   (proposal lines 36-40) is correct.
 - Confirmed `docs/ARCHITECTURE.md` has both ASCII `ADAPTERS:` boxes
   (lines 35, 59) and many prose path references (lines 97, 111-115,
   146, 202, 212, 220, 227, 301, 356, 401, 414, 420, 429, 437, 520);
   captured by proposal line 41-42.

### 🔴 Outstanding
 - **MISSING specs from "Modified Capabilities"** (serious — normative
   requirements would become inconsistent post-rename). Four specs in
   `openspec/specs/` contain SHALL/SHALL-NOT requirements that hard-code
   `yascheduler.adapters.*` paths but are NOT in the proposal's modified
   list:
   * `use-cases/spec.md` lines 34, 76, 97, 133, 141, 156 — e.g.
     "It SHALL NOT import from `yascheduler.adapters` at runtime".
   * `orchestrator/spec.md` lines 23, 49 — "SHALL NOT import ...
     from `yascheduler.adapters` at runtime" + matching scenario.
   * `domain-exceptions/spec.md` lines 150, 152, 159, 164 —
     "SHALL NOT export `CloudError` from `yascheduler.adapters.cloud`"
     with import scenarios.
   * `uow-not-initialized-error/spec.md` line 12 — "SHALL provide a
     `UnitOfWorkNotInitializedError` ... in
     `yascheduler.adapters.persistence.exceptions`".
   Each of these spec texts must be rewritten `adapters` → `infra` in
   the same change, otherwise `openspec validate --all --json` (and the
   AGENTS.md "update relevant OpenSpec requirements in the same change"
   rule) will fail or the specs will lie about the implementation.
   Fix: add `use-cases`, `orchestrator`, `domain-exceptions`, and
   `uow-not-initialized-error` to "Modified Capabilities" with one-line
   descriptions, and create matching delta specs.

 - **`ignore_imports` factual error in pyproject.toml scope** (serious —
   the proposal states config changes that do not exist). The proposal's
   "What Changes" (lines 30-32) and "Impact" (line 124-125) both assert
   that `pyproject.toml` has "2 `ignore_imports` edges" of the form
   `yascheduler.application.{consume_task,orchestrator} -> yascheduler.adapters`
   that need rewriting. The actual `pyproject.toml` line 131 reads
   `ignore_imports = []` — the list is EMPTY. Those two edges exist only
   as normative text in `package-facades/spec.md` (the "Documented
   residual edges" requirement at lines 203-229 and "Broad ignore_imports
   tradeoff" at lines 329-344); they were apparently removed from the
   actual config at some point.
   Fix: (a) drop the "2 `ignore_imports` edges" claim from the
   pyproject.toml scope in both "What Changes" and "Impact"; the
   pyproject.toml delta is actually "6 scripts + 1 layers label + 1
   package-data key". (b) Make sure the `package-facades` delta spec
   updates the SPEC TEXT that references those edges
   (`yascheduler.adapters` → `yascheduler.infra`), independent of
   whether pyproject.toml currently encodes them.

 - **Over-claimed Modified Capabilities whose spec text has no
   `yascheduler.adapters` references** (minor, but worth flagging to
   avoid empty delta specs):
   * `dependency-injection/spec.md` uses the word "adapters" only
     conceptually (e.g. "instantiates only the adapters it needs",
     "`adapters` or `configs` dicts"); it never hard-codes a
     `yascheduler.adapters` path. The di.py implementation change is
     real, but the spec text needs no rewrite. Either drop from the
     Modified list, or explicitly state that the delta spec adds a NEW
     requirement pinning the new path.
   * `testing-infrastructure/spec.md` contains zero `adapters`
     references (only `tests/unit/`, `pyproject.toml`, `conftest.py`).
     The spec delta would be empty. Either drop or justify.

 - **`_resolve_adapter` attribution ambiguity** (minor). The
   `dependency-injection` Modified-Capability entry (proposal lines
   79-84) describes the `_resolve_adapter` carve-out becoming
   `from .infra.cloud.adapters import _resolve_adapter`, but this
   carve-out is the R2 carve-out specified in `package-facades/spec.md`
   lines 317-327, not in `dependency-injection`. The proposal does say
   parenthetically "R2 carve-out in `package-facades`", so it isn't
   strictly wrong, but the same change is described twice. Clarify that
   the `_resolve_adapter` deep-path rewrite is owned by the
   `package-facades` delta (where the carve-out is specified); the
   `dependency-injection` entry should only describe the di.py import
   line change.

 - **File-count estimates slightly overstated** (cosmetic). Proposal
   Impact says "~80 source files under `yascheduler/adapters/` move"
   plus "~20 files outside" plus "~20 test files". A grep for
   `yascheduler\.adapters|yascheduler/adapters` across `yascheduler/`
   and `tests/` returns 61 distinct files total (incl. the moved tree).
   Order of magnitude is fine; consider softening "~80" or dropping the
   precise tally.

## proposal Round 2 — 2026-06-23

### 🔴 Fixed
 - **`ignore_imports` false claim removed** (was Round 1 serious). Proposal
   lines 34-40 now correctly state the array is empty
   (`ignore_imports = []`, verified against `pyproject.toml` line 131) and
   that the two residual R3 edges
   (`yascheduler.application.{consume_task,orchestrator} -> yascheduler.adapters`)
   live only in `package-facades/spec.md` text (verified at spec lines
   203-210). The clarification is accurate and internally consistent. The
   "Build config" Impact bullet (lines 142-144) now correctly says "6
   scripts + 1 layers label + 1 package-data key" with the empty
   `ignore_imports` explicitly called out.
 - **4 missing specs added to Modified Capabilities** (was Round 1 serious).
   `use-cases`, `orchestrator`, `domain-exceptions`, `uow-not-initialized-error`
   are now listed (proposal lines 114-130). Each entry correctly notes that
   the spec's normative path references are rewritten from
   `yascheduler.adapters…` to `yascheduler.infra…` while preserving
   SHALL/SHALL-NOT semantics. Verified each spec has the claimed path
   references: `use-cases` (6 refs), `orchestrator` (2 refs),
   `domain-exceptions` (4 refs), `uow-not-initialized-error` (1 ref).
 - **`dependency-injection` and `testing-infrastructure` dropped from
   Modified** (was Round 1 minor). Confirmed via grep that neither spec
   text contains any `yascheduler.adapters` or `yascheduler/adapters` path
   reference — `dependency-injection` uses "adapters" only conceptually
   (e.g. "only the adapters it needs"); `testing-infrastructure` has zero
   "adapters" hits. Dropping them avoids empty delta specs.
 - **`_resolve_adapter` attribution de-duplicated** (was Round 1 minor).
   The carve-out is now mentioned only under `package-facades` (proposal
   line 83: `from .infra.cloud.adapters import _resolve_adapter`). It is
   no longer mentioned under `dependency-injection` because that capability
   was dropped from the Modified list.
 - **File-count estimates corrected** (was Round 1 cosmetic). Verified
   against actual tree: 64 non-cache files under `yascheduler/adapters/`
   (41 .py + 23 .sql), 7 files outside with import or comment references
   (di.py, daemon_systemd.py, daemon_sysv.py = real imports; client.py,
   config/__init__.py, domain/exceptions.py, domain/model.py = comment
   refs only), 20 test files. Proposal's "~61/handful/~18" is within "~"
   tolerance for all three figures.

### 🟡 Addressed
 - **Completeness cross-check of Modified Capabilities** (fresh full sweep).
   Grepped all of `openspec/specs/` for `yascheduler\.adapters`,
   `yascheduler/adapters`, and `adapters/` path references. Exactly 18
   specs have path references; all 18 are in the proposal's Modified
   Capabilities list. No spec with path references is missing. The list
   is complete: `cli-commands`, `cloud-providers`, `cloud-provisioner`,
   `cloud-wrapper`, `domain-exceptions`, `e2e-testing`, `orchestrator`,
   `package-facades`, `platform-adapters`, `postgres-uow`,
   `remote-machine-wrapper`, `sql-queries`, `ssh-gateway`,
   `test-db-integration`, `testing-unit`, `uow-not-initialized-error`,
   `use-cases`, `webhook-handler`.
 - Verified `package-data` key claim: `pyproject.toml` line 140 reads
   `"yascheduler.adapters.persistence.sql" = ["**/*.sql"]` — matches the
   proposal's description of the rename target.
 - Verified AiiDA entrypoint (line 57) does NOT reference `adapters` —
   "BREAKING (internal import paths only)" framing remains accurate.

### 🔴 Outstanding
 - none

### New minor nits introduced by the edits (non-blocking)
 - Proposal lines 34-40: the `ignore_imports` clarification is a standalone
   paragraph (not a bullet) sitting between the `pyproject.toml` bullet
   (ends line 32) and the `knowledge-graph.xml` bullet (line 41). Slightly
   awkward structurally; consider making it a sub-bullet under the
   `pyproject.toml` entry or a top-level bullet.
 - Proposal line 38: the parenthetical "(and the matching `package-data`
   key)" is slightly confusing — the `package-data` key is unrelated to
   the R3 edges; it reads as if the key "matches" the edges. Consider
   splitting the sentence so the two items (spec text update + package-data
   key rename) are clearly independent.
 - Proposal line 138: "for comment references only" at the end of the
   parenthetical file list is scope-ambiguous — unclear whether it
   modifies all 7 named files or just the trailing group. Intended meaning
   (verified against source) is: `di.py`/`daemon_systemd.py`/`daemon_sysv.py`
   have real import changes; `client.py`/`config/__init__.py`/`domain/*`
   have comment-only references. A comma or semicolon before
   "for comment references only" would disambiguate.

## design Round 1 — 2026-06-23

### 🔴 Fixed
 - (none yet — this is the first design review pass)

### 🟡 Addressed
 - Verified Decision 6 against `pyproject.toml`: the `layers` contract
   (lines 125-130) has `yascheduler.adapters` as the FIRST entry only;
   the other three (`application`, `domain`, `shared`) are unchanged.
   "First entry only" claim is accurate. The `forbidden` contract
   (lines 133-137) references `yascheduler.shared` and
   `yascheduler.config` — neither moves, so no break. ✓
 - Verified `ignore_imports = []` at `pyproject.toml:131`. Decision 6's
   claim that the array is empty and unchanged is correct, and matches
   the frozen proposal's Round-2 fix. ✓
 - Verified the two `adapters.py` basenames exist at
   `yascheduler/adapters/cloud/adapters.py` and
   `yascheduler/adapters/ssh/platform/adapters.py`. Decision 2's
   anchoring claim is correct: pattern `yascheduler/adapters/` does NOT
   match `cloud/adapters.py` or `ssh/platform/adapters.py` (no
   `yascheduler/` prefix on those basenames), and
   `yascheduler.adapters` does NOT match `CloudAdapter` /
   `RemoteMachineAdapter` / `M-ADAPTERS` / `M-CLOUD-ADAPTERS-NEW` /
   `M-PLATFORM-ADAPTERS`. ✓
 - Verified Decision 7 (single commit, no shim) justification: the
   AGENTS.md public-interface stability list covers `class Yascheduler`,
   CLI command names, INI format, DB schema, AiiDA entrypoint — NOT
   internal module paths. The AiiDA entrypoint
   (`yascheduler.aiida_plugin:YaScheduler`, pyproject.toml:57) does not
   reference `adapters`. Rollback via `git revert` of one atomic commit
   is sound. ✓
 - Verified `openspec validate --all --json` will pass: the 8 specs with
   literal `yascheduler.adapters`/`yascheduler/adapters` hits
   (domain-exceptions, orchestrator, package-facades, postgres-uow,
   testing-unit, uow-not-initialized-error, use-cases, webhook-handler)
   are all in the proposal's Modified list. ✓
 - Cross-checked Decision 3 excluded set: `openspec/changes/archive/**`,
   this change's own dir, `CHANGELOG.md`, `.venv/**`, `.devenv/**`,
   `__pycache__/**` are all sensible exclusions. The CHANGELOG.md
   decision ("rename entry goes in a NEW section, not by rewriting old
   entries") is consistent — `changelog_incremental = true` in
   pyproject.toml means commitizen appends, it does not rewrite. ✓

### 🔴 Outstanding
 - **CRITICAL: Decision 2's two patterns miss `from .adapters` relative
   imports** (serious — the package will not import after `git mv`).
   There are 8 `from .adapters` / `from .adapters.cli` references in
   source. The design's patterns
   (`yascheduler.adapters` dotted, `yascheduler/adapters/` slashed)
   require the `yascheduler` prefix and match NONE of them. After
   `git mv yascheduler/adapters yascheduler/infra`, 4 of these become
   broken imports that must be rewritten to `from .infra`:
     * `yascheduler/di.py:33` — `from .adapters import (...)`
     * `yascheduler/di.py:40` — `from .adapters.cloud import resolve_adapter`
     * `yascheduler/daemon_sysv.py:31` — `from .adapters.cli import daemonize`
     * `yascheduler/daemon_systemd.py:26` — `from .adapters.cli import daemonize`
   The OTHER 4 `from .adapters` references are sibling-module imports
   of the PRESERVED `adapters.py` basename and MUST NOT be touched:
     * `yascheduler/adapters/cloud/__init__.py:36`
     * `yascheduler/adapters/cloud/provider_selection.py:29`
     * `yascheduler/adapters/cloud/manager.py:58`
     * `yascheduler/adapters/ssh/platform/__init__.py:18`
   A naive third pattern `from .adapters` → `from .infra` would WRONGLY
   rewrite these 4 sibling imports and break them. The design must call
   out this ambiguity and specify context-aware handling (the 4
   layer-dir imports are in files OUTSIDE the moved tree; the 4
   sibling-module imports are in files INSIDE `cloud/` and
   `ssh/platform/` and refer to the local `adapters.py`). The
   proposal's Impact (line 134-136) lists `di.py`, `daemon_systemd.py`,
   `daemon_sysv.py` as files with import changes, so the scope is
   acknowledged — but the design's mechanical procedure does not
   cover them.

 - **CRITICAL: Decision 2's two patterns miss `adapters/` relative
   slash-form references** (serious — specs and docs will lie about
   paths post-rename). The design claims "Two anchored literal
   patterns cover the full surface" — this is false. 10 of the 18
   specs in the proposal's Modified Capabilities contain path refs in
   the form `adapters/cloud/`, `adapters/ssh/`, `adapters/persistence/...`,
   `adapters/cli/...` WITHOUT the `yascheduler/` prefix, and NEITHER
   pattern matches them:
     * `cli-commands/spec.md:36,38` (`adapters/cli/init.py`,
       `adapters/persistence/postgres_schema.py`)
     * `cloud-providers/spec.md:6,13,30` (`adapters/cloud/`,
       `adapters/cloud/providers/`)
     * `cloud-provisioner/spec.md:91,125,127,131,135`
     * `cloud-wrapper/spec.md:6,15,16`
     * `remote-machine-wrapper/spec.md:7,16`
     * `ssh-gateway/spec.md:154,157,161`
     * `sql-queries/spec.md:11` (`adapters/persistence/sql/`)
     * `platform-adapters/spec.md:6,13` (`adapters/ssh/platform/`)
     * `test-db-integration/spec.md:10`
     * `e2e-testing/spec.md:9`
     * `package-facades/spec.md:86` (Scenario heading `adapters/cli/__init__.py`)
   The same gap exists in `docs/ARCHITECTURE.md` (lines 111-115, 301,
   356, 401, 520 — ASCII diagram + prose) and in
   `docs/knowledge-graph.xml` annotation PURPOSE attributes (lines 85-90:
   `adapters/cli/submit.py` etc.; lines 205-206: `relocated from
   adapters/cloud`; line ~850: `adapters/ssh/ consumers`). Source
   comments are also affected: `yascheduler/domain/exceptions.py:32`
   (`relocated from adapters/cloud/manager.py`) and
   `yascheduler/client.py:53` (`# FIXME: move to adapters/api?`).

 - **CRITICAL: Risk #1's verification grep provides false confidence**
   (serious — compounds the two issues above). The post-rewrite check
   `grep -rn "yascheduler.adapters"` will return ZERO matches even
   though all the `from .adapters` and `adapters/` references above
   remain un-rewritten. The grep must be broadened to also catch
   `\.adapters\b` (relative imports) and standalone `adapters/` (slash
   form), with explicit allow-listing of the 4 sibling-module
   `from .adapters` imports and the `adapters.py` basenames.

 - **Decision 5 factual error: PURPOSE attributes DO contain paths**
   (serious for graph consistency). Decision 5 says "Preserve all
   `<annotation>` PURPOSE attributes (they describe behavior, not
   location)" — but lines 85-90 of `knowledge-graph.xml` embed file
   paths in PURPOSE text:
     `<fn-submit PURPOSE="Submit task via AiiDA script (adapters/cli/submit.py)" />`
   and lines 205-206 say "relocated from adapters/cloud". These are
   location references, not behavior descriptions; leaving them as
   `adapters/...` after the directory becomes `infra/` is misleading.
   Fix: rewrite path tokens inside PURPOSE attributes too (the
   `adapters/` relative-form pattern from the issue above covers this).

 - **Decision 5 imprecision on `grace_check.py` failure mode** (minor
   but worth correcting). Decision 5 says paths "must match the
   filesystem or `grace_check.py` fails". Per `scripts/grace_check.py`
   `_check_path_existence` (lines 491-503), a `<path>` not found on
   disk emits a WARNING (`findings.warning`), not an error; `_report`
   (lines 933-949) returns exit 1 only on ERRORS. So `grace_check.py`
   does NOT fail (exit non-zero) on path mismatch — it warns and
   exits 0. This does not affect correctness (the design's plan updates
   `<path>` to match the new location, so no warning fires), but the
   stated rationale is inaccurate.

 - **Migration plan step 5 is under-specified for the `from .adapters`
   ambiguity** (serious — ties to the first outstanding issue). Step 5
   says "`LINKS:`/`MODULE_MAP` references to paths are rewritten by
   pattern 1 if dotted or pattern 2 if slashed" — but the 4
   `from .adapters` layer-dir imports match neither pattern, and the 4
   sibling-module `from .adapters` imports must be explicitly
   preserved. The migration plan needs an explicit step for the 4
   manual `.adapters` → `.infra` edits in `di.py`,
   `daemon_systemd.py`, `daemon_sysv.py`, with a note that the
   in-cloud and in-platform `.adapters` imports are intentionally
   left alone.

## design Round 2 — 2026-06-23

### 🔴 Fixed
 - **Decision 2 expanded from 2 to 4 patterns** (was Round 1 critical).
   Pattern 3 (five subpackage-anchored bare-slash forms:
   `adapters/{cloud,ssh,persistence,cli,notifier}` → `infra/...`) and
   pattern 4 (`from .adapters` → `from .infra` as an explicit allow-list)
   are now specified. Verified the anchoring claim: the five anchors do
   NOT match the preserved `adapters.py` basenames — `cloud/adapters.py`
   and `ssh/platform/adapters.py` do not contain any
   `adapters/<subpackage>` substring (the basename is `adapters.py`,
   followed by `.py`, not by a subpackage name). The four sibling
   `from .adapters` imports (which resolve to the preserved basename)
   are explicitly excluded from pattern 4. ✓
 - **Risk #1 verification grep broadened to 4 greps** (was Round 1
   critical). Grep #1 (dotted), #2 (prefix-slash), #3 (bare-slash via
   the five subpackage names), #4 (`from .adapters` with explicit
   four-match allow-list check) are all present (design lines 283-286).
   Confirmed grep #4's scope is `yascheduler/` only (tests have no
   `from .adapters`), so it will return exactly the 4 sibling imports
   post-rewrite. ✓
 - **Decision 5 PURPOSE attribute handling fixed** (was Round 1
   serious). Design lines 207-211 now explicitly state PURPOSE text
   embeds file paths (e.g. `(adapters/cli/submit.py)`) and that only
   the path token is rewritten via pattern 3 while behavioral prose is
   preserved. The `grace_check.py` claim is corrected (lines 228-229):
   it warns on path mismatch, does not hard-fail — verified against
   `scripts/grace_check.py` `_check_path_existence` (warning, not
   error). ✓
 - **Migration Plan step 3 expanded** (was Round 1 serious). Step 3
   (lines 369-377) now documents the allow-list for pattern 4
   (`di.py:33,40`, `daemon_sysv.py:31`, `daemon_systemd.py:26`) and the
   four DO-NOT-TOUCH sibling imports inside `yascheduler/infra/`. ✓
 - **Verified pattern 4 allow-list completeness**. Ran
   `grep -rn "from \.adapters" --include="*.py" yascheduler/ tests/`:
   exactly 8 matches. The 4 to rewrite (`di.py:33`, `di.py:40`,
   `daemon_sysv.py:31`, `daemon_systemd.py:26`) are all in the design's
   allow-list. The 4 to preserve (`adapters/cloud/__init__.py:36`,
   `adapters/cloud/provider_selection.py:29`, `adapters/cloud/manager.py:58`,
   `adapters/ssh/platform/__init__.py:18`) are all in the design's
   DO-NOT-TOUCH list. No other file outside the renamed tree has
   `from .adapters`. ✓
 - **Verified pattern 3 covers all bare-slash refs in spec prose and
   PURPOSE text**. Ran
   `grep -rn "adapters/" --include="*.md" --include="*.xml" openspec/specs/ docs/`:
   every match in `openspec/specs/` and every PURPOSE-embedded path in
   `docs/knowledge-graph.xml` (lines 85-90, 205-206, 850) starts with
   one of the five subpackage names. No spec/PURPOSE reference uses a
   different subpackage or no subpackage. The five anchors are
   sufficient for the spec + PURPOSE surface. ✓

### 🟡 Addressed
 - Pattern 3's alternatives-considered (design lines 135-138) correctly
   explains why a single `adapters/` → `infra/` would corrupt
   `adapters/ssh/platform/adapters.py` → `infra/ssh/platform/infra.py`,
   justifying the subpackage anchoring. ✓
 - Pattern 4's alternatives-considered (lines 139-146) correctly
   rejects both a global `from .adapters` rewrite (breaks 4 siblings)
   and promoting the siblings to absolute imports (violates the R1
   relative-import rule). ✓
 - The design's Risks section now has a dedicated pattern-4 risk entry
   (lines 308-317) mirroring the allow-list logic. Internally
   consistent with Decision 2 and Migration Plan step 3. ✓
 - Cross-checked Decision 4 (18 Modified Capabilities, path-rewrite
   only, semantics preserved) against the frozen proposal's Modified
   list — same 18 specs, same "rewrite path tokens, preserve
   SHALL/SHALL NOT" framing. Consistent. ✓

### 🔴 Outstanding
 - **Pattern 3 misses two standalone `adapters/` directory references
   in `docs/ARCHITECTURE.md` ASCII diagrams** (serious — completeness
   gap; was flagged in Round 1 lines 356+401, not resolved by pattern
   3). Two lines reference the directory by its bare name with NO
   subpackage following:
     * `docs/ARCHITECTURE.md:356` — `adapters/     → may import domain/, application/ (via facades)`
       (inside the §3.6 import-rules ```txt block)
     * `docs/ARCHITECTURE.md:401` — `├── adapters/`
       (inside the §4 project-structure ```txt tree, line 402 also has
       `# adapters layer facade` as an inline comment)
   None of the four patterns catch them: pattern 1 needs a dot,
   pattern 2 needs the `yascheduler/` prefix, pattern 3 needs a
   subpackage name after `adapters/`, pattern 4 needs `from `. The
   design's pattern 3 description (line 101-104) claims coverage of
   "`docs/ARCHITECTURE.md` prose", but these two ASCII-diagram lines
   are real directory labels that no pattern covers. Verification
   grep #3 (`adapters/cloud|adapters/ssh|...`) also will not catch
   them, so the post-rewrite check gives false confidence. After the
   rename, both lines will still say `adapters/` while the directory
   is `infra/` — directly contradicting the user's "everything
   carefully updated everywhere" intent. (Note: no automated check
   fails — `grace_check.py` and `openspec validate` do not inspect
   ARCHITECTURE.md — but the docs will be inconsistent with the
   filesystem.) The other 5 ARCHITECTURE.md bare-slash refs flagged
   in Round 1 (lines 111-115, 301, 520) ARE now covered by pattern 3
   because they carry a subpackage name.
   Fix: add a fifth manual edit for `docs/ARCHITECTURE.md` lines 356
   and 401 (the two ASCII diagrams where `adapters/` is a standalone
   directory label), OR scope a pattern 5 (`adapters/` at end-of-line
   or followed by whitespace) to `docs/ARCHITECTURE.md`, OR list these
   two lines explicitly in Migration Plan step 3 as manual edits.
   Also broaden verification grep #3 to catch standalone `adapters/`
   in `docs/ARCHITECTURE.md` (e.g. a fifth grep
   `grep -n "adapters/$\|adapters/ " docs/ARCHITECTURE.md`).

### New minor nits introduced by the edits (non-blocking)
 - **"four-file allow-list" terminology error** (factual). Decision 2
   pattern 4 (line 115: "the four top-level files"), Migration Plan
   step 3 (line 369: "four-file allow-list"), and Risks (line 311:
   "explicit four-file allow-list") all call pattern 4 a four-FILE
   allow-list, but it is a THREE-file allow-list (`di.py`,
   `daemon_sysv.py`, `daemon_systemd.py`) covering four IMPORT LINES
   (`di.py:33`, `di.py:40`, `daemon_sysv.py:31`, `daemon_systemd.py:26`).
   The "four" is the line count, not the file count. An implementer
   reading "four-file allow-list" may look for a missing fourth file.
   Fix: say "three-file allow-list covering four import lines" or
   "four-line allow-list across three files".
 - **Two FIXME comments with bare `adapters` not acknowledged**
   (completeness, non-blocking). `yascheduler/client.py:53`
   (`# FIXME: move to adapters/api?`) and
   `yascheduler/config/__init__.py:39`
   (`# FIXME: move this module to adapters / reimplement in adapters`)
   contain bare `adapters` references not caught by any pattern. The
   first is a hypothetical future path (`adapters/api` does not
   exist); the second is a conceptual layer name. Whether to rewrite
   them is debatable, but Round 1 flagged `client.py:53` and the
   design still does not acknowledge either. The design should either
   state they are intentionally left (conceptual/hypothetical) or list
   them as manual review items, so the implementer does not
   discover them post-hoc and wonder if they were missed.

## specs+tasks Round 1 — 2026-06-23
### 🔴 Fixed
 - None — batch is clean.

### 🟡 Addressed
 - **Tasks.md 3.2 lists ARCHITECTURE.md lines 356, 401 under "prefix-slash" (pattern 2), but these lines are bare `adapters/` without `yascheduler/` prefix.** Pattern 2's sed won't match them. Tasks.md 4.1 lists them more accurately as "standalone `adapters/` directory label." Since both tasks enumerate explicit line numbers, an implementer won't miss them — but the heading mismatch could confuse someone running a mechanical sed for the section's pattern. Low risk; the design's Round 2 already flagged these two lines as needing manual attention, and the tasks mitigate by explicit enumeration.
 - **Tasks.md 4.1 is under "pattern 3: bare-slash-form" heading (`adapters/<subpkg>`), but the standalone `adapters/` on lines 356/401 won't match pattern 3's subpackage-anchored search either.** Same root cause as above. Both entries resolve to the same manual edits; no real implementation risk.

### 🔴 Outstanding
 - none
