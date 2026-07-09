# 36fda7a — Add parm need_raid

**Date:** 2026-07-05
**Author:** alinzh

Added the `need_raid` config flag so cloud-init can skip RAID0 setup for
plans where NVMe is already the main disk (e.g. `vbm-8c-132gb`).

## Files changed (4 files, +61/-22)

### Modified

- **`yascheduler/config/cloud.py`** (+2) — added `need_raid: bool =
  make_default_field(True)` field to `ConfigCloudVultr`. Added
  `need_raid=sec.getboolean(fmt("need_raid"), fallback=True)` in
  `from_config_parser_section`.

- **`yascheduler/clouds/vultr.py`** (+46/-22) — `build_baremetal_user_data`
  now takes `need_raid: bool = True`:
  - When `True`: `mdadm` added to packages, `runcmd` includes RAID0
    create + mkfs + mount `/data` + `mdadm.conf` + `update-initramfs`
    + `/dev/shm` 200G.
  - When `False`: `mdadm` excluded from packages, `runcmd` only does
    `mkdir -p /data` (on root disk) + ulimit + ScaLAPACK symlink.
    No RAID, no `/dev/shm` resize.
  - `vultr_create_node_sync` passes `cfg.need_raid` to
    `build_baremetal_user_data`.

- **`CLOUD.md`** (+34/-22) — new "RAID0 and disk setup" section
  documenting both modes. Bare-metal setup section updated to mark
  RAID0 and `/dev/shm` as "only when `vultr_need_raid = True`". Config
  example includes `vultr_need_raid = True`.

- **`yascheduler/data/yascheduler.conf`** (+1) — added
  `;vultr_need_raid = True` to the commented example.

## Why

`vbm-24c-256gb-amd` ships with unformatted NVMe drives requiring RAID0.
`vbm-8c-132gb` has NVMe as the main disk (already mounted at `/`).
Running `mdadm --create` on the system disk would destroy the OS. The
flag lets the same adapter work with both plan types.

In both cases `/data` is created — engines go to `/data/engines`, tasks
to `/data/tasks`, AiiDA work dir to `/data/aiida`.