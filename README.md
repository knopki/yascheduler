# Yet another computing scheduler & cloud orchestration engine

[![DOI](https://zenodo.org/badge/222936146.svg)](https://doi.org/10.5281/zenodo.7693555)
[![PyPI](https://img.shields.io/pypi/v/yascheduler.svg?style=flat)](https://pypi.org/project/yascheduler)
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Ftilde-lab%2Fyascheduler.svg?type=shield)](https://app.fossa.com/projects/git%2Bgithub.com%2Ftilde-lab%2Fyascheduler?ref=badge_shield)

**Yascheduler** is a simple job scheduler designed for submitting scientific
calculations and copying back the results from the computing clouds.

Currently it supports several scientific simulation codes in chemistry and solid
state physics. Any other scientific simulation code can be supported via the
declarative control template system (see `yascheduler.conf` settings file).
There is an [example dummy C++ code](https://github.com/tilde-lab/dummy-engine)
with its configuration template.

## Installation

Use `pip` and PyPI: `pip install yascheduler`.

By default, no cloud connectors are installed.
To install the appropriate connector, use one of the commands:

- for Microsoft Azure: `pip install yascheduler[azure]`
- for UpCloud: `pip install yascheduler[upcloud]`

The last updates and bugfixes can be obtained cloning the repository:

```sh
git clone https://github.com/tilde-lab/yascheduler.git
pip install yascheduler/
```

The installation procedure creates the configuration file located at
`/etc/yascheduler/yascheduler.conf`.
The file contains credentials for Postgres database access, used directories,
cloud providers and scientific simulation codes (called *engines*).
Please check and amend this file with the correct credentials. The database
and the system service should then be initialized with `yainit` script.

## Usage

```python
from yascheduler import Yascheduler

yac = Yascheduler()
label = "test assignment"
engine = "pcrystal"
struct_input = str(...)  # simulation control file: crystal structure
setup_input = str(...)  # simulation control file: main setup, can include struct_input
result = yac.queue_submit_task(
    label, {"fort.34": struct_input, "INPUT": setup_input}, engine
)
print(result)
```

Or run directly in console with `yascheduler` (use a key `-l DEBUG` to change
the log level).

*Supervisor* config reads e.g.:

```ini
[program:scheduler]
command=/usr/local/bin/yascheduler
user=root
autostart=true
autorestart=true
stderr_logfile=/data/yascheduler.log
stdout_logfile=/data/yascheduler.log
```

File paths can be set using the environment variables:

- `YASCHEDULER_CONF_PATH`
  Configuration file.
  *Default*: `/etc/yascheduler/yascheduler.conf`

- `YASCHEDULER_LOG_PATH`
  Log file path.
  *Default*: `/var/log/yascheduler.log`

- `YASCHEDULER_PID_PATH`
  PID file.
  *Default*: `/var/run/yascheduler.pid`

## Configuration

Yascheduler reads its settings from an INI file. The file path is set by the
`YASCHEDULER_CONF_PATH` environment variable (see [Usage](#usage) above).

The file covers the PostgreSQL database, local daemon settings, remote SSH
defaults, cloud providers, and calculation engines. Every section, key, and
default is documented in **[docs/CONFIG.md](docs/CONFIG.md)**.

For cloud-provider-specific setup (Azure, VastAI, Vultr), see also
[docs/AZURE.md](docs/AZURE.md), [docs/VASTAI.md](docs/VASTAI.md),
[docs/VULTR.md](docs/VULTR.md).

## Aiida Integration

See the detailed instructions for the [MPDS-AiiDA-CRYSTAL
workflows](https://github.com/mpds-io/mpds-aiida) as well as the
[ansible-mpds](https://github.com/mpds-io/ansible-mpds) repository. In essence:

```sh
ssh aiidauser@localhost # important
reentry scan
verdi computer setup
verdi computer test $COMPUTER
verdi code setup
```

## License

[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Ftilde-lab%2Fyascheduler.svg?type=large)](https://app.fossa.com/projects/git%2Bgithub.com%2Ftilde-lab%2Fyascheduler?ref=badge_large)
