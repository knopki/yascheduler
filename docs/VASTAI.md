# VastAI

VastAI is a GPU marketplace for on-demand GPU instances. Yascheduler
automatically creates and deletes VastAI instances based on task demand.

## Setup

1. **Get a VastAI API key** from the [Console](https://cloud.vast.ai/).

2. **Configure `/etc/yascheduler/yascheduler.conf`** — add the following keys
  to the `[clouds]` section (defaults shown):

   ```ini
   [clouds]
   vastai_api_key = YOUR_VAST_API_KEY_HERE
   # Instance image. Determines launch mode and package manager (see below).
   vastai_image = pytorch/pytorch:2.2.2-cuda12.1-cudnn8-devel
   # System disk size in GB (>= 1).
   vastai_disk_gb = 80
   # Minimum GPU VRAM per instance in MB (>= 1024).
   vastai_min_vram_mb = 81920
   # Exact GPU count per instance (>= 1).
   vastai_num_gpus = 1
   # Max per-hour price (dph_total) in USD (>= 0). Offers above this are rejected.
   vastai_max_price_per_hr = 1.50
   # Max concurrent VastAI nodes (>= 0).
   vastai_max_nodes = 10
   # SSH username is ignored and always is "root"
   # vastai_user = root
   # Provider priority among enabled clouds (higher = preferred).
   vastai_priority = 0
   # Seconds an idle node is tolerated before disable/delete (>= 1).
   vastai_idle_tolerance = 300
   # Whether generated onstart does a package-manager upgrade (see Translation).
   vastai_package_upgrade = true
   # Custom onstart script **PATH**. Non-empty overrides cloud-init translation verbatim.
   vastai_onstart_script =
   # Docker run options
   vastai_docker_options = -e VARIABLE=1 -p 8384:8384
   # Jump host for SSH bastion access (optional).
   vastai_jump_user =
   vastai_jump_host =
   vastai_jump_port = 22
   ```

3. **Initialize**: run `yainit`.

4. **Start the yascheduler service.**

### KVM vs Docker

The launch mode is **auto-detected from `vastai_image`** — there is no explicit
config flag:

- The image name contains `vastai/kvm` → **KVM mode**
- Any other image → **Docker mode**.

Both modes return an SSH-accessible instance.

### Onstart script

- If `vastai_onstart_script` is non-empty, it is used **verbatim**.
- Otherwise a script is created with packages update and new packages install.
  Package manager is auto-detected, but only `apt-get` and `dnf` is supported.

### On-demand only

The provider searches **on-demand** offers only (`type == "on-demand"` in the
filter). Spot / interruptible pricing is **not** supported.

## Testing

- **E2E (live, env-gated)**: the live VastAI e2e is opt-in and skipped by
  default. It runs only when both environment variables are set:

  ```bash
  YASCHEDULER_TEST_VASTAI=1
  VAST_API_KEY=<your key>
  ```

It drives the full cycle (submit → autoscale → allocate → download → DONE →
idle deallocate) against a real VastAI account, with strong finally-cleanup
that best-effort deletes every observed instance id and asserts each is gone
via `GET /instances/{id}/` (404 expected); a survivor fails the test loudly.
