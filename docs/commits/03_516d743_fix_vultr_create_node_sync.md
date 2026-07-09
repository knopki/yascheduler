# 516d743 — Fix vultr_create_node_sync

**Date:** 2026-07-03
**Author:** alinzh

Replaced the naive `time.sleep(90)` with an active SSH auth retry loop
using paramiko. This was needed because bare metal opens the SSH port
before cloud-init finishes writing `authorized_keys`, causing
`Permission denied` on early connect attempts.

## Files changed (1 file, +59/-5)

### Modified

- **`yascheduler/clouds/vultr.py`** — in `vultr_create_node_sync`:
  - **Removed:** `time.sleep(90)` after SSH port opened.
  - **Added:** paramiko-based retry loop (12 attempts × 15 s):
    - Exports the asyncssh key to a tempfile (paramiko needs a file path).
    - `paramiko.Transport((ip, 22))` → `transport.connect(username=...,
      pkey=paramiko.RSAKey.from_private_key_file(...))`.
    - On success: logs "SSH auth OK on attempt N/12", breaks.
    - On failure: logs at debug level, `time.sleep(15)`, retries.
    - After 12 failures: raises `APIError`.
    - Tempfile cleaned up in `finally` block via `os.unlink`.

## Why

The first test run (b131184) failed with `Permission denied for user
root` — the scheduler connected too early, got denied, and immediately
created a new bare-metal instance. This happened 5 times, exhausting the
$1000/month Vultr account limit (each instance ~$725/month). The retry
loop waits for cloud-init to install the key instead of failing fast.

## Note

This commit introduced paramiko as an inline import inside the function
body. Reviewer @knopki pointed out that paramiko is not a project
dependency and asyncssh should be used instead. This was addressed later
in commit `36c19a0`.