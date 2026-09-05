# Vultr

Vultr provides **bare-metal** instances suitable for heavy `ab initio`
calculations (CRYSTAL Seebeck/TDF, FLEUR). This integration uses the Vultr REST
API v2 directly via `aiohttp` (no extra Python dependency is required —
`aiohttp` and `asyncssh` are already core dependencies).

## Setup

1. **Get a Vultr API key** — create one in the
  [Vultr customer portal](https://my.vultr.com/settings/#settingsapi).

2. **Configure `/etc/yascheduler/yascheduler.conf`** — add the following keys
  to the `[clouds]` section (defaults shown):

   ```ini
   [clouds]
   vultr_api_key = YOUR_VULTR_API_KEY
   # Datacenter region (Vultr API `region`).
   vultr_location = ams
   # Bare-metal plan id (Vultr API `plan`).
   vultr_server_type = vbm-24c-256gb-amd
   # Vultr OS id (integer, sent as `os_id`). 2136 = Debian 12 (bookworm), 2284 = Ubuntu 24.04 LTS x64.
   vultr_image_name = 2136
   # Set False for plans where NVMe is already the main disk (e.g. vbm-8c-132gb).
   vultr_need_raid = true
   # Max concurrent Vultr nodes (>= 0).
   vultr_max_nodes = 2
   # Seconds of idleness before auto-deletion (>= 1).
   vultr_idle_tolerance = 1800
   ```

## Defaults

The default plan is `vbm-24c-256gb-amd` (AMD EPYC 7443P, 24C/48T, 256 GB RAM,
2x 480 GB SSD + 2x 1.92 TB NVMe) in the `ams` location on Debian 12 (bookworm)
(`vultr_image_name=2136`, the Vultr OS id). Bare-metal provisioning is slow
(up to ~20 minutes), so `create_node_timeout` is set to 1200 s and `op_limit`
to 2.

> **Note:** `vultr_image_name=2136` is Debian 12 (bookworm) x64, better suited
> for headless bare-metal instances. Ubuntu 24.04 LTS x64 is `2284`. The
> cloud-init setup works on both, but Debian 12 is recommended for servers.

## RAID0 and disk setup (`vultr_need_raid`)

The `vultr_need_raid` flag controls whether cloud-init performs RAID0 NVMe
setup. It defaults to `True` (for `vbm-24c-256gb-amd`).

- **`vultr_need_raid = True`** (default, for `vbm-24c-256gb-amd`):
  RAID0 NVMe (`mdadm --create /dev/md0`), mount `/data`, resize `/dev/shm` to
  200G, install `mdadm`. Required because NVMe drives are unformatted on this
  plan.
- **`vultr_need_raid = False`** (for `vbm-8c-132gb` and similar):
  Skip RAID0. NVMe is already the main disk (mounted at `/`). Only `mkdir -p
  /data` is created on the root disk. `/dev/shm` is left at default (50% of
  RAM). No `mdadm` package installed.

In both cases `/data` is available for engines (`/data/engines`), tasks
(`/data/tasks`), and AiiDA work directory (`/data/aiida`).

## Bare-metal setup (automatic via cloud-init)

The following steps from the
[Vultr setup README][vultr_setup] are applied automatically via cloud-init
`user_data` on instance creation:

- **`mkdir /data`** — always created (on RAID0 mount or root disk).
- **RAID0 NVMe** (only when `vultr_need_raid = True`) — `mdadm --create
  /dev/md0` from `nvme0n1` + `nvme1n1`, `mkfs.ext4`, mount at `/data`,
  persist via `/etc/fstab`, save to `mdadm.conf` and `update-initramfs -u`.
- **`/dev/shm` 200G** (only when `vultr_need_raid = True`) — required by
  CRYSTAL pproperties for inter-process communication during parallel
  Seebeck/TDF runs.
- **ulimit 65536** — required by FLEUR/CRYSTAL parallel runs that open many
  files simultaneously.
- **ScaLAPACK symlinks** — `libscalapack-openmpi.so.2.1` and `.so.2.2` both
  symlinked to `.so.2.2.1`, expected by FLEUR and CRYSTAL.
- **apt packages** — `openmpi-bin`, `libopenmpi-dev`, `libscalapack-openmpi-dev`,
  `libxml2-dev`, `libblas-dev`, `liblapack-dev`, `build-essential`, `gfortran`,
  `cmake`, `git` (`mdadm` only when `vultr_need_raid = True`), plus
  engine-specific packages from `[engine.*]` `platform_packages`.

Engines are deployed to `/data/engines` (per `[remote] engines_dir`) by the
scheduler after the instance becomes active.

## Cost control

The default plan costs **$0.993/hour**. Nodes are deleted automatically after
`vultr_idle_tolerance` seconds of idleness (default 1800 s = 30 min) by the
existing `deallocator_producer`. Setting `vultr_idle_tolerance` too low may
cause frequent provisioning cycles; too high wastes money. Tune per your
workload pattern.

## Standalone test script

A standalone script is provided to verify the Vultr API and instance lifecycle
without running the full scheduler:

```sh
export VULTR_API_KEY='your_api_key_here'
python examples/vultr_test.py test
```

This creates a bare-metal instance, waits for it to become active, checks that
the SSH port is open, then deletes it. Use `--keep` to leave the instance
running, and `python examples/vultr_test.py list` / `delete --id <id>` to manage
instances manually.

[vultr_setup]: https://github.com/mpds-io/ab_initio_calculations/blob/main/scripts/vultr/README.md
