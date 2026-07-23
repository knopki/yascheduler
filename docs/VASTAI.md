# VastAI

VastAI is a GPU marketplace for on-demand GPU instances. Yascheduler
automatically creates and deletes VastAI instances based on task demand.

## Setup

1. **Get VastAI API key** from [Console](https://vast.ai/console/cli/)

2. **Install the VastAI connector**:

   ```bash
   pip install yascheduler
   ```

3. **Configure in `/etc/yascheduler/yascheduler.conf`**:
  Add to the `[clouds]` section:

   ```ini
   [clouds]
   vastai_api_key = YOUR_VAST_API_KEY_HERE
   vastai_image = pytorch/pytorch:2.2.2-cuda12.1-cudnn8-devel
   vastai_disk_gb = 80
   vastai_min_vram_mb = 81920
   vastai_num_gpus = 1
   vastai_max_price_per_hr = 1.50
   vastai_max_nodes = 10
   vastai_user = root
   vastai_priority = 0
   vastai_idle_tolerance = 300
   vastai_onstart_script =
   vastai_docker_options = -p 8384:8384
   vastai_jump_user =
   vastai_jump_host =
   ```

4. **Initialize**: Run `yainit`

5. **Start yascheduler service**

## Features

- **Automatic instance search** - Finds cheapest available GPU offers matching criteria
- **SSH readiness verification** - Waits for instances to be fully ready
- **Proper cleanup** - Instances are deleted automatically when idle
- **Async support** - Full integration with yascheduler's async patterns

## Notes

- Instances are created with `runtype: ssh_direct` for direct SSH access
- The `onstart_script` can be used to customize instance initialization
- Yascheduler automatically manages instance lifecycle - no manual intervention
  needed
