## Context

`run_daemon` (`yascheduler/entrypoints/cli/daemon_common.py:76-123`) is the async core shared by all three daemon entry points. Its tail is a bare `await orch.start()`:

```
async def run_daemon(config, logger):
    orch = await make_daemon(config, logger)        # http_session created here
    # ...register SIGTERM/SIGINT handlers...
    await orch.start()                              # ← no try/finally
```

`Orchestrator.start()` (`orchestrator.py:631-677`) ends with `await self._shutdown_barrier()`, which is `gather(*self._bg_jobs, return_exceptions=True)`. The 5 background jobs are: `_print_stats` and 4 `_create_producer_consumers` coordinators, each running `while not self._cancellation_event.is_set():` with a producer that opens a UoW (`async with self._uow_factory() as uow:`).

`Orchestrator.stop()` (`orchestrator.py:686-700`) is the only cleanup path:

```
async def stop(self):
    self._cancellation_event.set()
    for task in self._bg_jobs:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass       # ← ONLY CancelledError
    await self._clouds.stop()                     # ← no try/except
    await self._gateway.disconnect_all()          # ← no try/except
    if self._http_session is not None:            # ← not nulled after close
        await self._http_session.close()
```

`stop()` is called exclusively from `on_signal` (the SIGTERM/SIGINT handler registered at `daemon_common.py:107-118`). Two consequences:

1. **Normal `start()` return leaks.** If every bg job dies with a non-`CancelledError` (e.g. persistent DB outage: each producer's `async with self._uow_factory()` raises `pg8000.Error`), `gather(return_exceptions=True)` swallows the exceptions and `start()` returns. `run_daemon` then returns without ever calling `stop()` → asyncssh connections, `aiohttp.ClientSession` (created in `_setup_domain_events`, `di.py:109-120`), and cloud clients leak. The process exits via `asyncio.run` teardown with "Unclosed ..." warnings.

2. **Signal path breaks on pre-dead jobs.** If a bg job already died with a non-`CancelledError` before SIGTERM, `stop()`'s `await task` re-raises the original exception; `except asyncio.CancelledError` does not catch it → `stop()` aborts before reaching `clouds.stop()`/`disconnect_all()`/`http_session.close()`. Partial leak even on the signal path.

3. **`stop()` is not idempotent.** Double SIGTERM, or signal+finally (once the `try/finally` is added), can call `stop()` twice. `if self._http_session is not None` is not atomic across interleaved awaits on a single-threaded loop: two coroutines can both pass the check before either nulls the reference, then both call `close()` on the same session. A failing cleanup step (`clouds.stop()` raises) aborts the whole chain because the steps are not isolated.

`asyncio.CancelledError` is a `BaseException` (not `Exception`) since Python 3.8, and the repo requires `>=3.9` (`pyproject.toml`), so `except asyncio.CancelledError` and `except Exception` are two distinct, non-overlapping clauses.

## Goals / Non-Goals

**Goals:**
- `run_daemon` SHALL call `orch.stop()` on every exit path: normal `start()` return, `start()` raising, and signal. The signal handler still calls `stop()` first; the `finally` becomes a no-op.
- `Orchestrator.stop()` SHALL be idempotent: the cleanup body runs exactly once across concurrent, interleaved, or repeated callers. The second and later callers return immediately.
- `Orchestrator.stop()` SHALL be exception-safe: a background job that died with a non-`CancelledError` before shutdown SHALL NOT abort the cleanup chain; each cleanup step (`clouds.stop()`, `gateway.disconnect_all()`, `http_session.close()`) SHALL be isolated so one failing step does not skip the others; `http_session` SHALL be nulled after closing so a repeated call cannot close an already-closed session.
- Graceful shutdown semantics (`CancelledError` reaches the drain path) SHALL be preserved byte-for-byte.

**Non-Goals:**
- Registering worker tasks (the local `workers: set` inside `_create_producer_consumers`) in `self._bg_jobs` — that is the sibling change `fix-orchestrator-producer-silent-death`. This change assumes that change's worker registration may or may not have landed yet; it hardens `stop()` against any job (coordinator OR worker) dying with a non-`CancelledError`, which composes with the worker registration.
- Changing the producer/consumer resilience (try/except around `async for msg in producer():`) — also the sibling change. This change does not alter `_create_producer_consumers`' loop body.
- Changing the public API of `run_daemon` or `Orchestrator.stop` — signatures are unchanged; only the body and the surrounding `try/finally` change.
- A `_stopping` (vs `_stopped`) state that makes the second caller `await` the first's completion. The second caller returns immediately as a no-op. Both observed callers (`on_signal` then its own sweep; `run_daemon` then process exit) do not depend on resources being closed by the time their `await stop()` returns, so an instant no-op is safe.
- Persisting shutdown state across daemon restarts. `_stopped` is in-memory; a fresh `Orchestrator` starts with `_stopped = False`.

## Decisions

### D1: `try/finally` around `await orch.start()` in `run_daemon`

**Choice:** wrap `await orch.start()` in `try: ... finally: await orch.stop()`.

**Alternatives considered:**
- *Async context manager (`async with orch: await orch.start()`)* — requires adding `__aenter__/__aexit__` to `Orchestrator`, widening the public API for a single call site. Rejected (YAGNI): `try/finally` achieves the same guarantee with zero API surface change.
- *Make producers never raise (try/except inside producers)* — the sibling change's approach. Rejected as the primary fix here because even with resilient producers, `start()` could still return if all bg jobs happen to complete (e.g. a future bounded loop), and the signal path's dead-job-then-signal defect remains independent. This change and the sibling change are complementary, not substitutes.

**Rationale:** `try/finally` is the minimal, idiomatic Python guarantee that cleanup runs regardless of how the protected block exits. It composes with the signal handler: the handler calls `stop()` (first execution, body runs), `start()` then returns, `finally` calls `stop()` again (no-op due to the guard from D2).

### D2: `_stopped` boolean guard for single-execution idempotency

**Choice:** add `self._stopped = False` to `__init__`; at the top of `stop()`, `if self._stopped: return; self._stopped = True` with no `await` between the check and the set.

**Alternatives considered:**
- *`asyncio.Lock` around the body* — over-serializes: the second caller would block until the first finishes, when an instant no-op is sufficient and correct (see Non-Goals). Adds a lock primitive where a plain flag suffices.
- *`_stopping` + `await self._stop_complete_event.wait()`* — makes the second caller wait for full completion. Rejected: no observed caller depends on the post-condition "resources closed by the time `await stop()` returns". `on_signal` proceeds to its own `all_tasks` sweep and a 250ms sleep; `run_daemon`'s `finally` is the last statement before process exit. An instant no-op is correct and simpler.

**Rationale:** single-threaded asyncio has no true concurrency; coroutines only interleave at `await` points. A check-then-set with no intervening `await` is atomic with respect to other coroutines on the same loop. The first caller to reach `stop()` sets the flag synchronously; any caller that arrives later (sequentially or interleaved at an await boundary) sees `True` and returns immediately. The body therefore runs exactly once.

### D3: `except Exception` alongside `except asyncio.CancelledError` on `await task`

**Choice:** add `except Exception as e: self._log.debug(...)` after the existing `except asyncio.CancelledError: pass` in the per-task loop.

**Alternatives considered:**
- *`except BaseException: pass`* — catches `KeyboardInterrupt`/`SystemExit`, masking operator interrupts. Rejected: those should propagate. Also trips lint rules B036/B037.
- *Swallow silently without logging* — loses observability of why a bg job was in a dead state at shutdown. Rejected: a `debug`-level log is cheap and aids post-mortem.

**Rationale:** `CancelledError` is `BaseException` (3.8+), so `except Exception` does not catch it — the graceful-shutdown drain path is preserved. `except Exception` catches the realistic case of a bg job that died from a DB error, network error, or any application-level exception before shutdown, preventing that pre-existing exception from aborting the cleanup chain. Two distinct clauses, no overlap.

### D4: Per-step `try/except Exception` around each cleanup step

**Choice:** wrap `await self._clouds.stop()`, `await self._gateway.disconnect_all()`, and the `http_session.close()` block each in its own `try/except Exception as e: self._log.warning(...)`. Null `self._http_session = None` after closing.

**Alternatives considered:**
- *One outer try/except around all three* — a failure in `clouds.stop()` would still skip `disconnect_all()` and `http_session.close()`. Rejected: the whole point is step isolation.
- *No try/except (rely on the existing bare calls)* — leaves the abort-on-first-failure defect. Rejected.
- *Re-raise after logging* — would abort the chain. Rejected: cleanup steps are best-effort at shutdown; one failing step must not prevent the others.

**Rationale:** the three cleanup steps touch independent subsystems (cloud clients, SSH gateway, HTTP session). A failure in one (e.g. cloud API is unreachable so `clouds.stop()`'s `disconnect_all` partially fails) must not prevent closing the local SSH connections and the HTTP session. Logging at `warning` makes a partial cleanup visible to operators without aborting. Nulling `http_session` after `close()` makes the `if self._http_session is not None` guard meaningful across repeated calls (defense in depth with the D2 guard).

## Risks / Trade-offs

- **[Risk] A cleanup step silently fails and resources leak despite `stop()` "succeeding".** → Mitigation: each step logs at `warning` on failure; the operator-visible signal is the log line, consistent with the existing consumer-error logging convention. No new alerting surface is introduced (out of scope).
- **[Risk] The instant-no-op `_stopped` guard returns before the first `stop()` has finished closing resources, and a caller depends on resources being closed.** → Mitigation: audited both callers — `on_signal` proceeds to `asyncio.all_tasks()` sweep + 250ms sleep (does not read resources); `run_daemon`'s `finally` is the last statement (process exits). Neither depends on the post-condition. If a future caller needs it, upgrade to `_stopping`+event (D2 alternative) then.
- **[Risk] `except Exception` on `await task` masks a genuine bug in a bg job.** → Mitigation: logged at `debug` with the exception; the original exception was already swallowed by `gather(return_exceptions=True)` in `_shutdown_barrier`, so this does not change observability of the bg job's death — it only prevents the pre-existing exception from aborting `stop()`. The bug surface is unchanged; only the cleanup abort is fixed.
- **[Risk] Composition with `fix-orchestrator-producer-silent-death` (which registers workers in `_bg_jobs`) doubles the task count `stop()` iterates.** → Mitigation: `stop()` iterates `self._bg_jobs` and cancels+awaits each; double-cancellation of a task (coordinator cancels its workers, `stop()` also cancels them) is idempotent in asyncio. No conflict. The `except Exception` from D3 makes the worker cancellation robust the same way it does for coordinators.
- **[Trade-off] `try/finally` in `run_daemon` means `stop()` is called even when `make_daemon` succeeds but `start()` raises before creating all bg jobs.** This is desirable: the early bg jobs (`_print_stats`, `conn_machine_co`) are already in `_bg_jobs` and would otherwise leak. `stop()` cancelling an empty/partial `_bg_jobs` set is a safe no-op.

## Migration Plan

Single-step, backward-compatible deploy:
1. Land the `Orchestrator.stop()` hardening (guard + `except Exception` + per-step isolation + null) and the `run_daemon` `try/finally` together.
2. No config, DB, or CLI surface change. No migration. Rollback is a plain revert.

No ordering dependency with `fix-orchestrator-producer-silent-death`: this change is correct with or without worker registration. If the sibling change lands first, `stop()` iterates a larger `_bg_jobs` set (coordinators + workers) — the `except Exception` from D3 applies uniformly. If this change lands first, `stop()` iterates only coordinators — still correct.

## Open Questions

- None blocking. The composition-with-sibling question raised in explore ("include orphaned workers?") is resolved: workers belong to the sibling change; this change is orthogonal and explicitly non-overlapping.