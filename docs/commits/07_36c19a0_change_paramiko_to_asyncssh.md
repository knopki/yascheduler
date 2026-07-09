# 36c19a0 — Change paramiko to asyncssh

**Date:** 2026-07-08
**Author:** alinzh

Replaced the paramiko-based SSH auth retry with asyncssh, the project's
existing SSH dependency.

## Files changed (1 file, +58/-50)

### Modified

- **`yascheduler/clouds/vultr.py`** (+58/-50):
  - **Added** `import asyncssh` at the top of the file (alongside the
    existing `from asyncssh.public_key import SSHKey as ASSHKey`).
  - **Added** two constants: `SSH_AUTH_ATTEMPTS = 12`,
    `SSH_AUTH_INTERVAL = 15`.
  - **Added** async helper `_check_ssh_auth(log, instance_id, ip_addr,
    key, username, attempts, interval)`:
    - Loops up to `attempts` times.
    - Each attempt: `asyncssh.connect(ip, port=22, username=...,
      client_keys=[key], known_hosts=None, connect_timeout=10)` wrapped
      in `asyncio.wait_for(..., timeout=15)`.
    - On success: logs "SSH auth OK on attempt N/12", returns `True`.
    - On failure: logs at debug, `await asyncio.sleep(interval)`.
    - Returns `False` if all attempts fail.
  - **Replaced** the entire paramiko block in `vultr_create_node_sync`
    (tempfile, `paramiko.Transport`, `paramiko.RSAKey.from_private_key_file`,
    `os.unlink`) with a single call:
      `ssh_ok = asyncio.run(_check_ssh_auth(...))`.
  - **Removed** inline `import os`, `import tempfile`, `import paramiko`.

## Why paramiko was problematic

1. **Not a project dependency** — paramiko was imported inline inside
   the function body, never added to `pyproject.toml`. asyncssh is the
   project's SSH library (used by `remote_machine/`).
2. **Tempfile on disk** — paramiko's `RSAKey.from_private_key_file`
   requires a file path. The key had to be exported to a temp file,
   `chmod 600`, then `os.unlink` in a `finally` block. asyncssh accepts
   the key object directly via `client_keys=[key]`.
3. **Inline imports** — reviewer asked to move imports to the top of the
   file. With asyncssh, `import asyncssh` is now at module level.

## The sync→async bridge

`vultr_create_node_sync` runs inside a `ThreadPoolExecutor` thread (via
`run_in_executor` from the async `vultr_create_node` wrapper). In that
thread there is no running event loop, so `asyncio.run()` is safe: it
creates a temporary loop, runs `_check_ssh_auth`, and tears it down.

`known_hosts=None` disables host key verification — the instance is
freshly created and has no known host key.

## Testing

The MgO/225 Seebeck pipeline was run end-to-end after this change:
- `asyncssh.connect` connected to the server (log: "Connected to SSH
  server at 95.179.187.128, port 22").
- First attempts got "Auth failed for user root" (cloud-init not done).
- Retry succeeded after ~90 seconds.
- Pipeline finished [0] with all 4 BoltzTraP output files.