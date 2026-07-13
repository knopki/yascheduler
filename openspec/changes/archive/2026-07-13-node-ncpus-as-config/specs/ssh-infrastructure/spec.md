## MODIFIED Requirements

### Requirement: Retry and backoff policy

The system SHALL apply `@my_backoff_exc()` (fibonacci, max_time=60,
`SSHRetryExc`) ONLY to idempotent operations: `get_cpu_cores` (pure read, cache
miss path) and connection establishment. The system SHALL NOT apply
`@my_backoff_exc()` to `run_bg` and SHALL NOT apply `@my_backoff_sftp()`
to `upload` or `download` — these are non-idempotent (a successful remote
side-effect followed by a lost client confirmation would produce a duplicate
on retry). `download_outputs` SHALL continue to use `my_backoff_sftp()` as
the per-file retry wrapper inside the per-file loop.

SSH connections SHALL be retried on transient failures using the `backoff`
library with fibonacci backoff and `max_time=60`. The repository SHALL use
a two-method pattern for `connect()`: inner method with
`@my_backoff_exc()` (retries on `SSHRetryExc`), outer `connect` translates
exhausted `(asyncssh.misc.Error, OSError)` to `MachineConnectionError`.

The retry on `get_cpu_cores` applies only on a cache miss (the first call in a
session lifetime, or the priming call from `SSHMachineRepository.connect`); once
the session has cached a value, subsequent calls return without invoking the
adapter and therefore without retry.

#### Scenario: get_cpu_cores retries on SSH failure (cache miss)

- **WHEN** `session.get_cpu_cores()` is called on a session whose cache is empty (miss) and the underlying adapter call fails with a retryable SSH exception
- **THEN** the operation is retried with fibonacci backoff up to 60 seconds (idempotent read — retry is safe); the successful result is stored in the session cache

#### Scenario: get_cpu_cores returns cached value without retry

- **WHEN** `session.get_cpu_cores()` is called on a session that has already cached a CPU count (cache hit) and the underlying adapter would fail
- **THEN** the cached value is returned immediately; the adapter is NOT invoked and no retry is attempted

## ADDED Requirements

### Requirement: SSHMachineSession memoizes CPU core discovery

`SSHMachineSession` SHALL memoize the result of CPU-core discovery per session
instance. CPU count is invariant for the lifetime of one SSH connection, so
repeated `get_cpu_cores()` calls within the same session SHALL return the cached
value without re-executing the remote command (`getconf _NPROCESSORS_ONLN` on
Linux, the PowerShell equivalent on Windows).

The cache SHALL be primed by the discovery already performed in
`SSHMachineRepository.connect`: after `connect` constructs the
`SSHMachineSession`, the CPU count it read via `adapter.get_cpu_cores(...)`
SHALL seed the session cache so the relocated `"CPUs count: %s"` log line (per
the `connected-machine-runtime-only` change) and the cache fill happen in one
step. The first `get_cpu_cores()` call on the session (e.g. from the
orchestrator's `_start_task_on_machine` fallback for a `Node.ncpus is None`
node) then returns the primed cached value with no SSH exec.

The cache lives for the session's lifetime only — there is no cross-session
cache. A reconnected session (new `SSHMachineSession` instance) starts with an
empty cache and re-discovers once. CPU hot-add during a live scheduler session
goes unobserved until reconnect; an operator who needs the scheduler to see
added CPUs without reconnecting SHALL set `ncpus` explicitly via `yasetnode ~N`.

#### Scenario: First get_cpu_cores call in a session invokes the adapter

- **WHEN** `session.get_cpu_cores()` is called on a session whose cache is empty (miss)
- **THEN** the underlying `adapter.get_cpu_cores(...)` is invoked exactly once and the result is stored in the session cache

#### Scenario: Second get_cpu_cores call in a session returns the cache

- **WHEN** `session.get_cpu_cores()` is called twice on the same session instance
- **THEN** the underlying `adapter.get_cpu_cores(...)` is invoked exactly once (on the first call); the second call returns the cached value without invoking the adapter

#### Scenario: connect primes the session cache

- **WHEN** `SSHMachineRepository.connect(node, ...)` constructs an `SSHMachineSession` and reads `ncpus` via `adapter.get_cpu_cores(...)`
- **THEN** the session cache is seeded with that value, and the first `session.get_cpu_cores()` call returns the primed value without a further adapter invocation

#### Scenario: Reconnected session re-discovers

- **WHEN** a session is closed and a new `SSHMachineSession` is constructed for the same `node_id` (reconnect)
- **THEN** the new session's cache is empty and the first `get_cpu_cores()` call re-invokes the adapter
