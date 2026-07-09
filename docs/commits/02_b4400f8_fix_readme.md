# b4400f8 — Fix README

**Date:** 2026-07-03
**Author:** alinzh

Corrected the OS description in CLOUD.md: `os_id=2284` is Ubuntu 24.04
LTS, not Debian 12 as originally stated.

## Files changed (1 file, +7/-3)

### Modified

- **`CLOUD.md`** — changed "Debian 12 (`os_id=2284`)" to "Ubuntu 24.04 LTS
  (`os_id=2284`)". Added a note block:
  > `os_id=2284` is Ubuntu 24.04 LTS x64, not Debian 12.
  > Debian 12 (bookworm) is `os_id=2136`. The cloud-init setup works on
  > both, but Ubuntu 24.04 is recommended (newer packages).

## Why

During the first test run, `ssh root@<ip>` showed `Ubuntu 24.04 LTS x64`
in `/etc/os-release`, not Debian 12. The Vultr API also reported
`os: "Ubuntu 24.04 LTS x64"` for `os_id=2284`. The README in
`ab_initio_calculations/scripts/vultr/` was using 2284 under the
assumption it was Debian 12, but the actual image is Ubuntu 24.04.

Cloud-init and all setup steps work identically on both, so no code
changes were needed — only documentation.