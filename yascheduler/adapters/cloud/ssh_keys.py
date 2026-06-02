# FILE: yascheduler/adapters/cloud/ssh_keys.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: SSH key generation, loading, and name extraction for cloud provisioning.
#   SCOPE: Load existing SSH key from keys_dir, generate new one if none found, extract key name.
#   DEPENDS: none
#   LINKS: M-CLOUD-PROVISIONER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   get_or_create_ssh_key  # Load existing SSH key or generate a new one
#   get_key_name           # Get SSHKey's name
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from CloudProvisionerImpl._get_ssh_key_sync (manager.py) and get_key_name (utils.py).
# END_CHANGE_SUMMARY

"""SSH key management for cloud provisioning"""

from __future__ import annotations

from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from asyncssh.public_key import SSHKey, generate_private_key, read_private_key

from .utils import get_rnd_name

if TYPE_CHECKING:
    import logging


# START_CONTRACT: get_or_create_ssh_key
#   PURPOSE: Load existing SSH key from keys_dir or generate a new one if none found.
#   INPUTS: { keys_dir: Path - directory to scan for existing keys / write new key }
#            { log: logging.Logger - logger for debug/info messages }
#   OUTPUTS: { SSHKey - loaded or freshly generated SSH key }
#   SIDE_EFFECTS: May write a new private key file to keys_dir if no existing key found.
#   LINKS: M-CLOUD-PROVISIONER
# END_CONTRACT: get_or_create_ssh_key
def get_or_create_ssh_key(keys_dir: Path, log: logging.Logger) -> SSHKey:
    """Load existing SSH key or generate a new one."""
    prefix = "yakey"
    # START_BLOCK_LOAD_EXISTING
    for filepath in keys_dir.iterdir():
        if not filepath.name.startswith(prefix) or not filepath.is_file():
            continue
        ssh_key = read_private_key(filepath)
        ssh_key.set_comment(filepath.name)
        log.debug(
            "[ssh_keys][get_or_create] loaded key=%s fingerprint=%s",
            filepath.name,
            ssh_key.get_fingerprint("md5"),
        )
        return ssh_key
    # END_BLOCK_LOAD_EXISTING

    # START_BLOCK_GENERATE_NEW
    key_name = get_rnd_name(prefix)
    filepath = keys_dir / key_name
    ssh_key = generate_private_key(alg_name="ssh-rsa", comment=key_name)
    ssh_key.write_private_key(filepath)
    filepath.chmod(0o600)
    ssh_key.set_comment(key_name)
    log.info(
        "[ssh_keys][get_or_create] generated key=%s fingerprint=%s",
        key_name,
        ssh_key.get_fingerprint("md5"),
    )
    # END_BLOCK_GENERATE_NEW
    return ssh_key


# START_CONTRACT: get_key_name
#   PURPOSE: Extract a human-readable name from an SSHKey instance.
#   INPUTS: { key: SSHKey - the SSH key to extract name from }
#   OUTPUTS: { str - filename, comment, or fingerprint (last resort) }
#   LINKS: M-CLOUD-PROVISIONER
# END_CONTRACT: get_key_name
def get_key_name(key: SSHKey) -> str:
    """Get SSHKey's name"""
    fname_opt = key.get_filename()
    key_filename = fname_opt.decode("utf-8") if fname_opt else None
    if key_filename:
        key_filename = PurePath(key_filename).name
    key_fingerprint = key.get_fingerprint("md5").split(":", maxsplit=1)[1]
    return key_filename or key.get_comment() or key_fingerprint
