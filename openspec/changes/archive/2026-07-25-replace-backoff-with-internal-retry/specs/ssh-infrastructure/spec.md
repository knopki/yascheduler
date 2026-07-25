## MODIFIED Requirements

### Requirement: Retry and backoff policy

**Reason**: Replace `backoff` library with internal async retry utility. Fibonacci wait strategy replaced with exponential backoff — both produce comparable retry counts within a 60s window (~7-8 attempts). All other retry semantics (`max_time=60`, exception filtering, `giveup`) are preserved.

The system SHALL apply retry with exponential backoff, `max_time=60`, to idempotent operations: `get_cpu_cores` (pure read, cache miss path) and connection establishment. `download_outputs` SHALL continue to use per-file SFTP retry (exponential, `max_time=60`) inside the per-file loop.

SSH connections SHALL be retried on transient failures using exponential backoff with `max_time=60`. Exhausted failures SHALL surface as `MachineConnectionError`.

The retry on `get_cpu_cores` applies only on a cache miss (the first call in a session lifetime, or the priming call from `SSHMachineRepository.connect`).

#### Scenario: get_cpu_cores retries on SSH failure (cache miss)

- **WHEN** `session.get_cpu_cores()` is called on a session whose cache is empty (miss) and the underlying adapter call fails with a retryable SSH exception
- **THEN** the operation is retried with exponential backoff up to 60 seconds (idempotent read — retry is safe); the successful result is stored in the session cache

#### Scenario: get_cpu_cores returns cached value without retry

- **WHEN** `session.get_cpu_cores()` is called on a session that has already cached a CPU count (cache hit) and the underlying adapter would fail
- **THEN** the cached value is returned immediately; the adapter is NOT invoked and no retry is attempted

### Requirement: SSHMachineSession implements MachineSession

**Reason**: Replace `backoff` library with internal async retry utility. Fibonacci → exponential backoff. Retry semantics unchanged.

`run_full` SHALL retry on retryable SSH errors with exponential backoff up to `max_time=60`. `setup_node(engines: EngineRepository) -> None` (async) SHALL delegate to `adapter.setup_node(...)`.

#### Scenario: Session owns its monitor task

- **WHEN** `session.install_monitor(...)` is called
- **THEN** the resulting `asyncio.Task` is stored on the session and is NOT registered in any repository-level dict

#### Scenario: Session.hostname stays sourced from node.hostname

- **WHEN** `SSHMachineSession` is constructed by `SSHMachineRepository.connect`
- **THEN** `session.hostname == node.hostname` (the session's transport-echo field is sourced from the Node parameter)

### Requirement: download_outputs per-file SFTP isolation and retry

**Reason**: Replace `backoff` library with internal async retry utility. Fibonacci → exponential backoff. Retry semantics unchanged.

A FRESH SFTP client SHALL be opened per file in the per-file loop. Each file's `sftp.get` SHALL be wrapped individually with per-file retry (exponential, `max_time=60`).

#### Scenario: Download task outputs with per-file SFTP isolation and retry

- **WHEN** `operations.download_outputs(session, remote_dir, local_dir, files, task_id)` is called
- **THEN** a FRESH SFTP client is opened per file in the loop, each file is downloaded with per-file retry, per-file exceptions are classified into `transient_errors` and `permanent_errors`, and `(local_folder=str(local_dir), remote_folder=remote_dir, transient_errors, permanent_errors)` is returned
