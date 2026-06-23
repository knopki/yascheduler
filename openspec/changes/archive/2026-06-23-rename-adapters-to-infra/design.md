## Context

`yascheduler/adapters/` is the outer ring of the hexagonal
architecture, holding five subpackages (`cli/`, `cloud/`, `notifier/`,
`persistence/`, `ssh/`, with `ssh/platform/` nested). It is referenced
by:

- ~61 files inside the directory (intra-layer relative imports +
  `# FILE:` GRACE-lite headers).
- ~7 files outside the directory that import from it at runtime
  (`di.py`, `client.py`, `daemon_systemd.py`, `daemon_sysv.py`,
  `config/__init__.py`, plus comment-only references in
  `domain/exceptions.py` and `domain/model.py`).
- ~18 test files with absolute imports and `patch("yascheduler.adapters…")`
  string targets.
- `pyproject.toml`: 6 `[project.scripts]` entry points, the
  `import-linter` `layers` contract top layer label, and the
  `[tool.setuptools.package-data]` key
  `"yascheduler.adapters.persistence.sql"`.
- `docs/ARCHITECTURE.md` (prose + two ASCII layer diagrams).
- `docs/knowledge-graph.xml` (every `<path>` child of the affected
  `M-*` module records).
- 18 OpenSpec specs in `openspec/specs/` whose text contains normative
  `yascheduler.adapters…` path references.

The rename is **mechanical and sense-preserving**: no behavior, no
public API, no schema, no class name, no module basename change. The
user explicitly framed it as cosmetic. The design's job is to pick the
safest mechanical procedure and the right set of search/replace
patterns so nothing is missed and nothing semantic is touched.

## Goals / Non-Goals

**Goals:**
- Move the directory `yascheduler/adapters/` → `yascheduler/infra/`
  with all contents preserved byte-for-byte (modulo the path
  rewrites inside the moved files).
- Rewrite every `yascheduler.adapters…` absolute import path in the
  tree to `yascheduler.infra…`.
- Update `pyproject.toml`, `docs/ARCHITECTURE.md`,
  `docs/knowledge-graph.xml`, and the 18 OpenSpec spec texts to the
  new path.
- Update GRACE-lite `# FILE:` headers and `MODULE_CONTRACT`/`MODULE_MAP`/
  `LINKS:`/`CHANGE_SUMMARY` annotations inside the moved files.
- Leave all public surfaces (CLI command names, `class Yascheduler`
  signatures, INI format, DB schema, AiiDA entrypoint key, class names
  `CloudAdapter`/`RemoteMachineAdapter`/`CloudProvisionerImpl`,
  module basenames like `adapters.py`) untouched.
- End state: `uv run pytest`, `uv run lint-imports`,
  `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run zuban check`, `python3 scripts/grace_check.py`, and
  `openspec validate --all --json` all pass.

**Non-Goals:**
- No rename of the in-layer classes/modules named "adapter"
  (`CloudAdapter`, `RemoteMachineAdapter`,
  `yascheduler/infra/cloud/adapters.py`,
  `yascheduler/infra/ssh/platform/adapters.py`).
- No change to the `layers` contract semantics, the `forbidden`
  contract, or the `ignore_imports` array (which is empty).
- No public API change of any kind.
- No dependency additions or removals.
- No test logic, fixture, or assertion changes — only import paths and
  `patch("…")` string targets.
- No rename of GRACE-lite module IDs (`M-ADAPTERS`, `M-CLOUD`,
  `M-SSH`, `M-PERSISTENCE`, `M-NOTIFIER`, `M-CLOUD-ADAPTERS-NEW`,
  `M-PLATFORM-ADAPTERS`) — they label concepts, not the directory.

## Decisions

### Decision 1: `git mv` the directory, then rewrite references in place

**Choice.** Use `git mv yascheduler/adapters yascheduler/infra` to move
the whole tree in one operation (preserves history), then run targeted
search/replace across the repo for the path references.

**Alternatives considered.**
- *Per-file copy + delete*: loses `git mv` history linkage, more
  error-prone, no benefit for a pure rename.
- *A single repo-wide `sed` over all paths*: risky — would also touch
  `openspec/changes/archive/` historical proposals, `.venv/` vendored
  copies, and `CHANGELOG.md` entries that record past states. We
  explicitly exclude those (see Decision 4).

**Why.** `git mv` is the atomic, history-preserving primitive. A
single move + targeted rewrites minimizes the diff surface and keeps
the rename reviewable as "directory moved, references updated."

### Decision 2: Four replacement patterns, applied in order

**Choice.** Apply four literal-string replacement patterns, in this
order:

1. `yascheduler.adapters` → `yascheduler.infra`  (matches the dotted
   import form: `yascheduler.adapters`, `yascheduler.adapters.cli`,
   `yascheduler.adapters.ssh.gateway`, etc.).
2. `yascheduler/adapters/` → `yascheduler/infra/`  (matches the
   slash-form with the package prefix: `# FILE:` headers,
   `docs/ARCHITECTURE.md` ASCII diagrams, `docs/knowledge-graph.xml`
   `<path>` elements).
3. Five subpackage-anchored slash patterns for the bare form
   (no `yascheduler/` prefix), used in OpenSpec spec prose,
   `docs/ARCHITECTURE.md` prose, and `knowledge-graph.xml`
   `<annotation>` PURPOSE text:
   - `adapters/cloud` → `infra/cloud`
   - `adapters/ssh` → `infra/ssh`
   - `adapters/persistence` → `infra/persistence`
   - `adapters/cli` → `infra/cli`
   - `adapters/notifier` → `infra/notifier`
   Anchoring on the subpackage name (`cloud`/`ssh`/`persistence`/`cli`/`notifier`)
   is what makes these patterns safe: they do NOT match the
   `adapters.py` basenames (no subpackage name follows `adapters` in
   `adapters.py` — it's followed by `.py` or end-of-string).
4. `from .adapters` → `from .infra`, but ONLY in the four top-level
   files where `.adapters` resolves to the package being renamed:
   `yascheduler/di.py` (lines 33, 40),
   `yascheduler/daemon_sysv.py` (line 31),
   `yascheduler/daemon_systemd.py` (line 26). This pattern is
   context-guarded: it must NOT be applied to the four in-layer files
   where `from .adapters` imports a sibling module whose basename is
   `adapters.py` (preserved):
   `yascheduler/adapters/cloud/__init__.py` (line 36),
   `yascheduler/adapters/cloud/provider_selection.py` (line 29),
   `yascheduler/adapters/cloud/manager.py` (line 58),
   `yascheduler/adapters/ssh/platform/__init__.py` (line 18). After
   the `git mv`, those four files are at
   `yascheduler/infra/cloud/__init__.py` etc., and their
   `from .adapters import ...` correctly resolves to the sibling
   `adapters.py` (e.g. `yascheduler/infra/cloud/adapters.py`), which
   keeps its basename. Rewriting those four would break the import.

**Alternatives considered.**
- *A single regex `\badapters\b`*: would over-match class names, module
  basenames, and prose. Rejected.
- *Pattern 3 as a single `adapters/` → `infra/`*: would corrupt
  `adapters/ssh/platform/adapters.py` into
  `infra/ssh/platform/infra.py` (the basename `adapters.py` would also
  be rewritten). Anchoring on the subpackage name avoids this.
- *Pattern 4 as a global `from .adapters` → `from .infra`*: would
  break the four sibling-module imports inside the renamed tree.
  Rejected in favor of the four-file explicit allow-list.
- *Promote the four sibling `from .adapters` to absolute
  `from yascheduler.infra.cloud.adapters import …`*: would violate
  the R1 within-package relative-import rule in `package-facades`.
  Rejected — leave them as `from .adapters import …` (sibling form,
  unchanged).

**Why.** Four anchored patterns cover the full surface. Patterns 1
and 2 are prefix-anchored on `yascheduler`; pattern 3 is anchored on
the subpackage name (so it skips `adapters.py` basenames); pattern 4
is an explicit four-file allow-list (so it skips the four
sibling-module imports). The order (dotted → slashed-with-prefix →
bare-slashed → relative) is the natural application order; patterns
1 and 2 are disjoint (dotted paths never contain `/` at the
separator, slash paths never contain `.` at the separator), pattern 3
only matches what 2 missed (bare forms without the `yascheduler/`
prefix), and pattern 4 is a manual allow-list applied last.

### Decision 3: Rewrite scope — included and excluded paths

**Included** (rewrite references):
- `yascheduler/**/*.py` (all source).
- `tests/**/*.py` (all tests, including `patch("…")` string targets).
- `pyproject.toml`.
- `docs/ARCHITECTURE.md`.
- `docs/knowledge-graph.xml`.
- `openspec/specs/**/*.md` (the 18 specs that reference
  `yascheduler.adapters…`).

**Excluded** (do NOT touch):
- `openspec/changes/archive/**` — archived proposals are historical
  records of past decisions; rewriting them would falsify history.
- `openspec/changes/rename-adapters-to-infra/**` — this change's own
  artifacts deliberately use the old path when describing the
  before-state and the new path when describing the after-state.
- `CHANGELOG.md` — records past releases; the rename entry goes in a
  NEW section, not by rewriting old entries.
- `.venv/**`, `.devenv/**`, `**/__pycache__/**` — vendored / build
  artifacts.
- Any prose that intentionally quotes the old path as a historical
  reference (none identified outside the archive, but reviewers
  should watch for it).

**Why.** A mechanical rename must not rewrite history. The included
set is the live, normative surface; the excluded set is the frozen
historical record or disposable build output.

### Decision 4: OpenSpec spec deltas — path rewrite, semantics preserved

**Choice.** For each of the 18 Modified Capabilities, the delta spec
rewrites the normative path references from `yascheduler.adapters…` to
`yascheduler.infra…` and leaves every SHALL / SHALL NOT / Scenario
verb untouched. No requirement is added, removed, or reworded in
semantics.

**Why.** The specs are contracts. The rename changes the *label* of
the layer, not its *role* or *rules*. Rewriting only the path tokens
keeps the delta minimal and reviewable, and preserves the contract's
force. A reviewer diffing the delta should see only
`s/adapters/infra/` on path lines.

### Decision 5: GRACE-lite `knowledge-graph.xml` — paths change, IDs stay

**Choice.** In `docs/knowledge-graph.xml`:
- Rewrite every `<path>yascheduler/adapters/…</path>` to
  `<path>yascheduler/infra/…</path>` (Decision 2 pattern 2).
- Rewrite every bare `adapters/<subpackage>/…` path embedded in
  `<annotation>` PURPOSE text (e.g.
  `<fn-submit PURPOSE="Submit task via AiiDA script (adapters/cli/submit.py)" />`)
  via Decision 2 pattern 3. These PURPOSE strings embed file paths
  alongside behavioral descriptions; only the path token changes.
- Preserve all `M-*` tag names (`M-ADAPTERS`, `M-CLOUD`,
  `M-CLOUD-ADAPTERS-NEW`, `M-SSH`, `M-PERSISTENCE`, `M-NOTIFIER`,
  `M-PLATFORM-ADAPTERS`, etc.) — they are concept IDs, not paths.
- Preserve all behavioral PURPOSE prose (the non-path words in a
  PURPOSE attribute); only the embedded file path tokens are
  rewritten.
- Update the prose comment banners that say "Adapters layer facade"
  only where they reference the directory path; keep the conceptual
  label "adapters layer" in prose where it refers to the architectural
  role (the prose can say "the adapters layer (directory
  `yascheduler/infra/`)" to keep the concept name while fixing the
  path).

**Why.** Module IDs are stable anchors used by `LINKS:` references in
source-file contracts; renaming them would cascade into every
contract's `LINKS:` line for no benefit. Paths, however, must match
the filesystem or `grace_check.py` emits warnings (it does not hard
fail on path mismatch, but mismatches are still drift to avoid).
`<annotation>` PURPOSE text embeds file paths (e.g. `(adapters/cli/submit.py)`)
as locator hints; rewriting only the path token keeps the behavioral
prose intact. Keeping the prose concept label "adapters layer"
alongside the new directory name preserves architectural vocabulary
without misleading the file-path validator.

### Decision 6: `pyproject.toml` — three mechanical edits

**Choice.**
1. Six `[project.scripts]` values: `yascheduler.adapters.cli.*` →
   `yascheduler.infra.cli.*`.
2. `layers` contract: `"yascheduler.adapters"` →
   `"yascheduler.infra"` (first entry only; the other three layers
   are unchanged).
3. `[tool.setuptools.package-data]` key:
   `"yascheduler.adapters.persistence.sql"` →
   `"yascheduler.infra.persistence.sql"`.

**Why.** These are the only `pyproject.toml` references to the old
path. The `ignore_imports = []` array is empty and unchanged. The
`forbidden` contract references `yascheduler.shared` and
`yascheduler.config`, neither of which moves.

### Decision 7: Single commit, no migration period

**Choice.** Land the rename as a single atomic change: directory move
+ all reference rewrites + spec deltas + docs in one commit. No
backward-compatibility shim, no deprecation period, no
`yascheduler.adapters` re-export alias.

**Alternatives considered.**
- *Shim: `yascheduler/adapters/__init__.py` re-exporting from
  `yascheduler.infra`*: would keep external imports working during a
  transition. Rejected because (a) the AGENTS.md public-interface
  stability rule covers `class Yascheduler`, CLI commands, INI
  format, DB schema, AiiDA entrypoint — NOT internal module paths;
  (b) there are no external consumers of `yascheduler.adapters` as a
  Python import path (the package is installed as `yascheduler`, and
  `pip install` consumers use `from yascheduler import Yascheduler`,
  not `from yascheduler.adapters import …`); (c) a shim would defeat
  the purpose of the rename (disambiguating the layer name) by
  keeping the old name alive.

**Why.** Internal import paths are not public API. The rename is
cheap, the test suite is the safety net, and a shim would add dead
code.

## Risks / Trade-offs

- **Risk**: a reference is missed, breaking an import or a
  `patch("…")` target at test time.
  → **Mitigation**: after the rewrite, run the verification greps and
  require zero UNEXPECTED matches:
  1. `grep -rn "yascheduler.adapters" --include="*.py" --include="*.toml" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/ openspec/specs/ pyproject.toml` — must be zero (catches dotted-form leftovers).
  2. `grep -rn "yascheduler/adapters/" --include="*.py" --include="*.toml" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/ openspec/specs/ pyproject.toml` — must be zero (catches prefix-slash leftovers).
  3. `grep -rn "adapters/cloud\|adapters/ssh\|adapters/persistence\|adapters/cli\|adapters/notifier" --include="*.py" --include="*.toml" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/ openspec/specs/ pyproject.toml` — must be zero (catches bare-slash-form leftovers in spec prose, docs prose, and PURPOSE text).
  4. `grep -rn "from \.adapters" --include="*.py" yascheduler/` — must return ONLY the four expected sibling-module imports inside `yascheduler/infra/` (`cloud/__init__.py`, `cloud/provider_selection.py`, `cloud/manager.py`, `ssh/platform/__init__.py`); any other match is a missed rewrite. The four matches must resolve to sibling `adapters.py` basenames, NOT to the old package.
  Then run `uv run pytest -m unit|integration|e2e`,
  `uv run lint-imports`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run zuban check`,
  `python3 scripts/grace_check.py`, and
  `openspec validate --all --json`.

- **Risk**: `git mv` of a directory with untracked `__pycache__/`
  leaves stray bytecode under the old path.
  → **Mitigation**: remove `yascheduler/adapters/__pycache__/` (and
  any nested `__pycache__/`) before the `git mv`. The move itself
  only touches tracked files.

- **Risk**: a `patch("yascheduler.adapters.ssh.gateway._detect_platform")`
  string target in a test is missed because it's inside a string
  literal, not an import.
  → **Mitigation**: pattern 1 (`yascheduler.adapters` →
  `yascheduler.infra`) operates on the full file content, not just
  import lines, so string-literal targets are rewritten in the same
  pass. The post-rewrite grep #1 is path-agnostic about whether the
  match is in an import or a string.

- **Risk**: pattern 4 (`from .adapters` → `from .infra`) is applied
  to one of the four sibling-module imports inside the renamed tree,
  breaking the import of `adapters.py` (the preserved basename).
  → **Mitigation**: pattern 4 is an explicit four-file allow-list
  (Decision 2). The four sibling imports
  (`cloud/__init__.py`, `cloud/provider_selection.py`,
  `cloud/manager.py`, `ssh/platform/__init__.py`) are NOT touched.
  Verification grep #4 confirms exactly those four matches remain and
  they resolve to sibling `adapters.py` basenames under
  `yascheduler/infra/`.

- **Risk**: `import-linter` `layers` contract fails because the
  `ignore_imports` residual edges (documented in `package-facades`
  spec text) are not reflected in `pyproject.toml`.
  → **Mitigation**: the `ignore_imports` array is already empty in
  `pyproject.toml`; the residual R3 edges are a spec-text
  documentation of a known R3 violation that is currently suppressed
  by the `layers` contract's default behavior (the edges are
  `yascheduler.application.{consume_task,orchestrator} ->
  yascheduler.adapters`). After the rename, if `lint-imports` starts
  flagging those edges, add the two `ignore_imports` entries with the
  new `yascheduler.infra` target — but only if the linter actually
  flags them. The spec text is the source of truth for *why* the
  edges exist; `pyproject.toml` is the source of truth for *whether*
  they are currently suppressed. Keep the two in sync after the
  rename.

- **Risk**: `docs/knowledge-graph.xml` prose says "Adapters layer
  facade" but the `<path>` now says `yascheduler/infra/`,
  confusing a reader.
  → **Mitigation**: Decision 5 keeps the prose concept label "adapters
  layer" (the architectural role) and updates only the path. The
  pairing "(adapters layer, directory `yascheduler/infra/`)" is
  intentional and matches how the architecture is described.

- **Trade-off**: the rename touches ~90 files for a purely cosmetic
  benefit. The benefit is disambiguation of the word "adapter" (which
  currently collides with `CloudAdapter`, `RemoteMachineAdapter`, and
  the `adapters.py` module basenames) and alignment with the
  "infrastructure" vocabulary already used in prose. The cost is one
  large mechanical diff. The user has judged the benefit worth the
  cost; the design minimizes the risk via the four-pattern rewrite and
  the exhaustive grep verification.

## Migration Plan

Single-step migration (no phased rollout):

1. Pre-move cleanup: remove `__pycache__/` directories under
   `yascheduler/adapters/`.
2. `git mv yascheduler/adapters yascheduler/infra`.
3. Apply the four replacement patterns (Decision 2) to the included
   scope (Decision 3):
   - `yascheduler/**/*.py`
   - `tests/**/*.py`
   - `pyproject.toml`
   - `docs/ARCHITECTURE.md`
   - `docs/knowledge-graph.xml`
   - `openspec/specs/**/*.md`
   Patterns 1 and 2 can run as global search/replace over the
   included scope. Pattern 3 runs over the same scope but matches the
   bare subpackage-anchored slash forms. Pattern 4 is a four-file
   allow-list: manually edit `yascheduler/di.py` (lines 33, 40),
   `yascheduler/daemon_sysv.py` (line 31),
   `yascheduler/daemon_systemd.py` (line 26) to change
   `from .adapters` → `from .infra`. Do NOT touch the four sibling
   `from .adapters` imports inside `yascheduler/infra/`
   (`cloud/__init__.py`, `cloud/provider_selection.py`,
   `cloud/manager.py`, `ssh/platform/__init__.py`) — they resolve to
   the preserved `adapters.py` basename.
4. Update the OpenSpec spec deltas (Decision 4) — create the 18
   delta spec files under
   `openspec/changes/rename-adapters-to-infra/specs/<name>/spec.md`.
5. Update GRACE-lite `# FILE:` headers and contract annotations inside
   the moved files (covered by pattern 2 of Decision 2 for the
   `# FILE:` line; `LINKS:`/`MODULE_MAP` references to paths are
   rewritten by pattern 1 if dotted or pattern 2 if slashed; bare
   slash forms in PURPOSE text by pattern 3).
6. Run the verification suite: the four greps in Risks #1 plus
   `uv run pytest -m unit|integration|e2e`, `uv run lint-imports`,
   `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run zuban check`, `python3 scripts/grace_check.py`, and
   `openspec validate --all --json`.
7. Commit as a single atomic commit per the user's later instruction
   (the orchestrator does NOT auto-commit).

**Rollback.** `git revert <commit>` restores the old directory and
all references in one step, because the change is a single atomic
commit. No partial state survives.

## Open Questions

None. The rename is fully determined by the user's framing
("mechanically, sense preserved, everything updated carefully") and
the two-pattern rewrite. Any edge case that surfaces during
implementation (e.g., a prose comment that quotes the old path as a
historical reference) is handled by the exclusion rules in
Decision 3 and reviewer judgment during the verify phase.