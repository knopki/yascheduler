## Context

Cloud provider modules (`az.py`, `hetzner.py`, `upcloud.py`) currently use a two-layer mechanism to handle missing SDKs:

1. **Module load time** — `try/except ImportError` wrapping SDK imports, setting `_*_AVAILABLE = True/False`.
2. **Function call time** — `if not _*_AVAILABLE: raise ImportError(msg)` at the top of every public create/delete function, plus conditional `RETRY_AZURE_ERRORS`/`ALL_AZURE_ERRORS` tuple definitions in `az.py`.

The adapter resolution layer (`resolve_adapter` in `adapters.py`) already catches `ImportError` from getter functions and logs a warning — this is the single entry point for all cloud adapter resolution. The `_*_AVAILABLE` layer is redundant because:

- Provider modules always load successfully (the `try/except` prevents module-level failure).
- The getter's inline import (`from .providers.az import az_create_node`) always succeeds because the module is already loaded.
- The actual `ImportError` would only surface if a provider module had a *different* missing dependency not caught by its own `try/except` — a scenario that has never occurred and would indicate a bug, not a graceful-degradation case.

This is dead code that adds maintenance surface (three providers, each with the same pattern, plus test patches) for zero behavioral benefit.

## Goals / Non-Goals

**Goals:**
- Remove the redundant `_*_AVAILABLE` pattern from `az.py`, `hetzner.py`, `upcloud.py`.
- Centralize graceful-skip responsibility in `resolve_adapter` — the only entry point for adapter resolution.
- Remove corresponding test patches.

**Non-Goals:**
- No behavioral change to how missing SDKs are handled — `resolve_adapter` continues to catch `ImportError` and log a warning.
- No changes to `resolve_adapter`, `vastai.py`, or any non-provider code.
- No dependency changes.

## Decisions

### Decision: Remove `_*_AVAILABLE` from provider modules

Provider modules lose the `try/except ImportError` block, the `_*_AVAILABLE` flag, and the `if not _*_AVAILABLE: raise ImportError(msg)` guard from every public function. SDK imports become top-level unconditional imports.

**Rationale**: The `_*_AVAILABLE` pattern is dead code — it never triggers because `resolve_adapter` is the only entry point and already handles `ImportError`. Removing it eliminates maintenance surface without behavioral change. Removing both layers (including `except ImportError` from `resolve_adapter`) would break graceful degradation — without `_*_AVAILABLE`, a missing SDK causes the provider module import to fail, and without the catch in `resolve_adapter`, that failure would crash the application.

### Decision: Remove conditional error tuples from `az.py`

`RETRY_AZURE_ERRORS` and `ALL_AZURE_ERRORS` become unconditional imports of the azure exception types.

**Rationale**: The conditional was needed only because the module guarded against missing SDK. With unconditional SDK imports, the exception types are always available when the module loads.

### Decision: No change to `resolve_adapter`

`resolve_adapter`'s `except ImportError` catch remains. After removing `_*_AVAILABLE`, this catch becomes the **sole** mechanism for graceful degradation — a missing SDK causes the provider module import to fail, and `resolve_adapter` catches it.

### Decision: No change to `vastai.py`

VastAI already has no `_*_AVAILABLE` pattern. Its dependencies (`aiohttp`, `backoff`) are declared as hard dependencies in `pyproject.toml`.

### Decision: Update test patches

`tests/unit/test_cloud_provider_create_delete.py` — remove `patch` calls that set `_*_AVAILABLE = True`. Tests that assert `if not _*_AVAILABLE: raise ImportError` are removed (they tested dead code). All other provider tests are unchanged.

## Risks / Trade-offs

- **Risk**: A provider module has a syntax error or broken transitive dependency → `ImportError` at module load → `resolve_adapter` catches it → provider silently skipped. **Mitigation**: This is the same behavior as before (the `_*_AVAILABLE` pattern caught the same case). The warning log makes it observable.
- **Trade-off**: Provider modules become harder to import in isolation without the SDK installed. Previously, `from yascheduler.infra.cloud.providers.az import az_create_node` would succeed (module loads, `_AZURE_AVAILABLE = False`). Now it raises `ImportError`. **Acceptance**: This is acceptable because `resolve_adapter` is the only intended entry point, and tests run with SDKs installed.
