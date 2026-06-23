## 1. Code removal

- [x] 1.1 In `yascheduler/di.py`, delete the `CLIDeps.query` method, its
      surrounding `# START_CONTRACT: CLIDeps.query` / `# END_CONTRACT:
      CLIDeps.query` block, and the `# FIXME: vestigial ...` comment above it
      (currently lines 98-109).
- [x] 1.2 In `yascheduler/di.py` `MODULE_MAP`, change the `CLIDeps` line from
      "CLI submit and query operations" to "CLI submit operations".
- [x] 1.3 In `yascheduler/di.py` `START_CONTRACT: CLIDeps` block, drop
      `query` from the PURPOSE line ("Lightweight dependency container for CLI
      submit and query operations." → "...for CLI submit operations."). Also
      scan the `START_MODULE_CONTRACT` SCOPE line and edit only if it mentions
      `query` (currently it lists `CLIDeps dataclass` without `query`, so
      likely a no-op).
- [x] 1.4 In `yascheduler/di.py`, update the existing `START_CHANGE_SUMMARY`
      block: insert a new `LAST_CHANGE: v5.2.0 - Remove vestigial
      CLIDeps.query (zero production callers; encoded as follow-up in
      2026-06-23-client-query-uow).` line, demote the current `LAST_CHANGE`
      to `PREVIOUS_CHANGE`. Bump `# VERSION:` to `5.2.0`.

## 2. Test removal

- [x] 2.1 In `tests/unit/test_di.py`, delete
      `TestCLIDeps::test_query_uses_uow_factory` (the method body, the
      `@pytest.mark.asyncio` decorator above it, and any blank-line separator
      that would otherwise leave two blank lines between methods).
- [x] 2.2 Update the `TestCLIDeps` class docstring from "constructor, submit,
      query" to "constructor, submit".
- [x] 2.3 Update the file's `START_MODULE_CONTRACT` SCOPE line and the
      `TestCLIDeps` mention in the `START_MODULE_MAP`-equivalent header block
      to drop `query`.

## 3. Knowledge graph

- [x] 3.1 In `docs/knowledge-graph.xml`, change the `class-CLIDeps` PURPOSE
      attribute from "Lightweight dependency container for CLI submit and
      query" to "Lightweight dependency container for CLI submit" (currently
      around line 413). No M-ID, `<depends>`, or `<CrossLink>` change.

## 4. Verification

- [x] 4.1 Run `uv run pytest -m unit -q` and confirm no regressions,
      specifically `tests/unit/test_di.py` and `tests/unit/test_client_query.py`
      pass. The `TestCLIDeps` suite should still have the constructor and
      submit tests.
- [x] 4.2 Run `uv run ruff check . && uv run ruff format --check .` to confirm
      no lint/format drift from the deletion.
- [x] 4.3 Run `uv run lint-imports` to confirm the deletion does not leave any
      unused or misordered imports (defensive — no imports are removed by this
      change, but the check is cheap and on the project's required list).
- [x] 4.4 Run `python3 scripts/grace_check.py` and confirm exit 0 (no stale
      anchors referencing the removed `START_CONTRACT: CLIDeps.query`).
- [x] 4.5 Run `openspec validate --all --json` and confirm it passes with the
      two new spec deltas in this change directory.

## 5. Spec sync (optional, defer to archive)

- [x] 5.1 Do NOT modify `openspec/specs/dependency-injection/spec.md` or
      `openspec/specs/testing-unit/spec.md` in this step — those are updated
      from the delta specs during archive via `/opsx-sync` or the archive
      flow. Confirm the deltas in
      `openspec/changes/drop-cli-deps-query/specs/*/spec.md` are the source of
      truth and the main specs remain untouched until archive.
