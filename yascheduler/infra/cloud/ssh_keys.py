"""SSH key management for cloud provisioning."""
# region MODULE_CONTRACT
# PURPOSE: Ensure a valid SSH key exists (load existing or generate new) so cloud VM allocations never fail on missing credentials and key names are consistently formatted for provider APIs.
# SCOPE: Load existing SSH key from keys_dir, generate new one if none found, extract key name.
# DEPENDENCIES: USES API: asyncssh for key generation and serialization; READS: private key files from keys_dir; WRITES: private key file to keys_dir
# KEYWORDS: ssh key, generate, load, key name, cloud provisioning
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from pathlib import Path, PurePath

from asyncssh.public_key import SSHKey, generate_private_key, read_private_key

from .utils import get_rnd_name

__all__ = ["get_key_name", "get_or_create_ssh_key"]
logger = logging.getLogger(__name__)


# region FUNC_get_or_create_ssh_key
# PURPOSE: Load an existing SSH key from disk or generate a fresh one so cloud VM creation always has credentials available without manual key setup.
# ENSURES: May write a new private key file to keys_dir if no existing key found.
def get_or_create_ssh_key(keys_dir: Path) -> SSHKey:
    """Load existing SSH key or generate a new one."""
    keys_dir.mkdir(parents=True, exist_ok=True)
    prefix = "yakey"
    # region BLOCK_load_existing
    for filepath in keys_dir.iterdir():
        if not filepath.name.startswith(prefix) or not filepath.is_file():
            continue
        ssh_key = read_private_key(filepath)
        ssh_key.set_comment(filepath.name)
        logger.debug(
            "LOADED_KEY",
            extra={
                "key_name": filepath.name,
                "fingerprint": ssh_key.get_fingerprint("md5"),
            },
        )
        return ssh_key
    # endregion BLOCK_load_existing

    # region BLOCK_generate_new
    key_name = get_rnd_name(prefix)
    filepath = keys_dir / key_name
    ssh_key = generate_private_key(alg_name="ssh-rsa", comment=key_name)
    ssh_key.write_private_key(filepath)
    filepath.chmod(0o600)
    ssh_key.set_comment(key_name)
    logger.info(
        "generated ssh key=%s fingerprint=%s",
        key_name,
        ssh_key.get_fingerprint("md5"),
    )
    # endregion BLOCK_generate_new
    return ssh_key


# endregion FUNC_get_or_create_ssh_key


# region FUNC_get_key_name
# PURPOSE: Extract a human-readable label from an SSHKey so cloud provider APIs (Hetzner, Azure) can register it with a consistent name.
# ENSURES: Returns filename, comment, or fingerprint (last resort).
def get_key_name(key: SSHKey) -> str:
    """Get SSHKey's name."""
    fname_opt = key.get_filename()
    key_filename = fname_opt.decode("utf-8") if fname_opt else None
    if key_filename:
        key_filename = PurePath(key_filename).name
    key_fingerprint = key.get_fingerprint("md5").split(":", maxsplit=1)[1]
    return key_filename or key.get_comment() or key_fingerprint


# endregion FUNC_get_key_name
