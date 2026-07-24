## Why

Cloud provider modules (`az.py`, `hetzner.py`, `upcloud.py`) use a two-layer mechanism to handle missing SDKs:

1. **Module load time** — `try/except ImportError` wrapping SDK imports, setting `_*_AVAILABLE = True/False`.
2. **Function call time** — `if not _*_AVAILABLE: raise ImportError(msg)` at the top of every public create/delete function, plus conditional `RETRY_AZURE_ERRORS`/`ALL_AZURE_ERRORS` tuple definitions.

Meanwhile, `resolve_adapter` in `adapters.py` already catches `ImportError` from the getter functions and logs a warning — this is the single entry point for all cloud adapter resolution.

The `_*_AVAILABLE` layer is redundant: the provider modules always load successfully (the `try/except` prevents module-level failure), and the getter's inline import (`from .providers.az import az_create_node`) always succeeds because the module is already loaded. The actual `ImportError` would only surface if a provider module had a *different* missing dependency not caught by its own `try/except` — a scenario that has never occurred and would indicate a bug, not a graceful-degradation case.

This is dead code that adds maintenance surface (three providers, each with the same pattern, plus test patches) for zero behavioral benefit.

## What Changes

- **Remove** the `try/except ImportError` block and `_*_AVAILABLE` flag from `yascheduler/infra/cloud/providers/az.py`, `hetzner.py`, and `upcloud.py`. SDK imports become top-level unconditional imports.
- **Remove** the `if not _*_AVAILABLE: raise ImportError(msg)` guard from every public function in those three modules.
- **Remove** the conditional `RETRY_AZURE_ERRORS`/`ALL_AZURE_ERRORS` tuple definitions in `az.py` — these become unconditional imports of the azure exception types (the SDK is now a hard import dependency of the module).
- **No change** to `resolve_adapter` in `adapters.py` — it remains the single mechanism that catches `ImportError` from getter functions and logs a warning.
- **No change** to `vastai.py` — it already has no `_*_AVAILABLE` pattern.
- **Update** `tests/unit/test_cloud_provider_create_delete.py` — remove the `patch` calls that set `_*_AVAILABLE = True` (no longer needed since the modules import SDKs unconditionally).

## Non-Goals

- No behavioral change to how missing SDKs are handled — `resolve_adapter` continues to catch `ImportError` and log a warning.
- No changes to `resolve_adapter`, `vastai.py`, or any non-provider code.
- No dependency changes.

## Capabilities

### New Capabilities

*None.*

### Modified Capabilities

- `cloud` (spec): behavior unchanged — optional SDKs are still handled gracefully via `resolve_adapter`'s `ImportError` catch. The spec requirement "Optional provider SDKs SHALL be handled gracefully" remains satisfied. Delta spec created to confirm the requirement is unchanged.

## Impact

- **Code**: `yascheduler/infra/cloud/providers/az.py`, `hetzner.py`, `upcloud.py` — remove `_*_AVAILABLE` pattern, unconditional SDK imports, unconditional exception tuple definitions.
- **Specs**: `openspec/changes/simplify-cloud-adapter-loading/specs/cloud/spec.md` — delta spec confirming the graceful-skip requirement is unchanged.
- **Tests**: `tests/unit/test_cloud_provider_create_delete.py` — remove `_*_AVAILABLE` patches.
- **Public API, DB schema, INI format, CLI surface**: unchanged.
- **Dependencies**: unchanged.
- **Other providers**: untouched.
