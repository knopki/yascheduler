#!/usr/bin/env python3
# ruff: noqa: D103, S603, S607, T201
"""Dev environment manager for yascheduler.

Manages PostgreSQL + sshd containers, renders yascheduler.conf (merge-only —
never clobbers user-added engines or cloud sections), bootstraps the DB
schema, registers the sshd node, and runs the daemon or CLI tools.

    ./dev.py up          bootstrap + run daemon in foreground
    ./dev.py down        stop + remove containers (keep DB volume)
    ./dev.py run <tool>  uv run <tool> with dev config (e.g. yanodes)
    ./dev.py reinit      wipe DB volume + re-bootstrap

Config lands in yascheduler.conf (gitignored); runtime data in .run/ (gitignored).
"""
# region MODULE_CONTRACT
# PURPOSE: Give a contributor a one-command dev sandbox (PostgreSQL + sshd target + daemon on host) so iterating on yascheduler does not require manual container juggling or production resources.
# SCOPE:
# - Container lifecycle (ctr run/rm) for postgres:16-alpine + serversideup/docker-ssh via docker or podman, whichever is found first in PATH.
# - Render yascheduler.conf via ConfigParser merge — preserves user-added engines and cloud sections.
# - DB schema + migrations bootstrap and sshd node registration.
# - Foreground daemon launcher and CLI-tool wrapper.
# - NOT: production deployment, multi-node pools, cloud-provider provisioning.
# INVARIANTS:
# - yascheduler.conf and .run/ are gitignored; never committed.
# - bootstrap() is idempotent — re-running dev.py up is safe.
# - Node registration tolerates "already in DB" so the sandbox can be re-bootstrapped without manual cleanup.
# DEPENDENCIES: USES API: docker OR podman CLI (first match in PATH), uv, yascheduler CLI (yainit, yasetnode, yascheduler).
# RATIONALE:
# - Q: Why direct `run` instead of docker compose?
#   A: Compose would be a thin declarative layer over two long-lived containers; a single script keeps all orchestration in one readable place and avoids a separate compose.yaml file.
# - Q: Why execvpe into uv for the daemon instead of subprocess.run?
#   A: Process replacement keeps Ctrl-C flowing straight to the daemon without an intermediary Python process buffering signals.
# - Q: Why auto-detect docker vs podman rather than letting the user configure it?
#   A: podman is CLI-compatible with the subset we use (run/rm/inspect/volume + --health-*), so detection lets the script work on podman-only hosts (common on Fedora/RHEL/CentOS) with zero configuration.
# KEYWORDS: dev, sandbox, container, podman, docker, postgres, sshd, bootstrap, daemon, foreground
# endregion MODULE_CONTRACT

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from configparser import ConfigParser
from functools import cache
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / ".run"
CONF_PATH = ROOT / "yascheduler.conf"
KEYS_DIR = RUN_DIR / "keys"
SSH_DIR = RUN_DIR / "ssh"
ENGINES_DIR = RUN_DIR / "engines"

DB_CTR = "yascheduler-db"
SSHD_CTR = "yascheduler-sshd"
DB_VOLUME = "yascheduler-db-data"

POSTGRES_IMAGE = "docker.io/library/postgres:16-alpine"
SSHD_IMAGE = "docker.io/serversideup/docker-ssh"

# Searched in order; the first match in PATH wins. docker and podman expose a
# CLI-compatible subset (run/rm/inspect/volume + --health-*), so callers below
# do not branch on which runtime was selected.
_RUNTIME_CANDIDATES = ("podman", "docker")

_TEST_SHELL = {
    "platforms": "linux",
    "deploy_local_files": "run.sh",
    "spawn": "{engine_path}/run.sh",
    "check_pname": "sleep",
    "sleep_interval": "1",
    "input_files": "1.input",
    "output_files": "1.input.out",
}


def die(msg: str) -> NoReturn:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


# region FUNC_detect_runtime
# PURPOSE: Pick the first available container runtime from _RUNTIME_CANDIDATES so the script runs on docker- or podman-only hosts without configuration.
# ENSURES: Returns a non-empty runtime name present in PATH, or aborts via die() if none is found.
# RATIONALE:
# - Q: Why cache via @cache rather than call shutil.which() each time?
#   A: The runtime does not change mid-process; caching avoids repeated PATH scans on every ctr() call.
@cache
def detect_runtime() -> str:
    for candidate in _RUNTIME_CANDIDATES:
        if shutil.which(candidate):
            return candidate
    die(f"no container runtime found (looked for: {', '.join(_RUNTIME_CANDIDATES)})")


# endregion FUNC_detect_runtime


def ctr(*args: str, **kw) -> subprocess.CompletedProcess:  # noqa: ANN003
    return subprocess.run([detect_runtime(), *args], **kw)  # noqa: PLW1510


def ctr_status(name: str) -> str | None:
    r = ctr("inspect", "-f", "{{.State.Status}}", name, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def wait_healthy(name: str, label: str, timeout: int = 60) -> None:
    print(f"Waiting for {label}...", end="", flush=True)
    for _ in range(timeout):
        r = ctr(
            "inspect",
            "-f",
            "{{.State.Health.Status}}",
            name,
            capture_output=True,
            text=True,
        )
        if r.stdout.strip() == "healthy":
            print(" ready")
            return
        print(".", end="", flush=True)
        time.sleep(1)
    print(" timeout")
    die(f"{label} did not become healthy in {timeout}s")


def uv(
    *args: str, capture: bool = False, check: bool = True
) -> subprocess.CompletedProcess:
    env = dict(os.environ, YASCHEDULER_CONF_PATH=str(CONF_PATH))
    return subprocess.run(
        ["uv", "run", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=capture,
        check=check,
    )


# region FUNC_ensure_ssh_key
# PURPOSE: Provision the dev SSH keypair and wire it into the daemon's keys_dir so passwordless auth to the sshd container works on first run and survives re-runs.
# RATIONALE:
# - Q: Why symlink only the private key into keys_dir, leaving the .pub behind in .run/ssh?
#   A: yascheduler's list_private_keys() scans keys_dir and treats every file as a private key — a stray .pub or authorized_keys there would break key loading.
def ensure_ssh_key() -> None:
    SSH_DIR.mkdir(parents=True, exist_ok=True)
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    key = SSH_DIR / "id_ed25519"
    if not key.exists():
        print("Generating SSH keypair...")
        docker_ok = subprocess.run(  # noqa: PLW1510
            [
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                "yascheduler-dev",
                "-f",
                str(key),
            ],
        )
        if docker_ok.returncode != 0:
            die("ssh-keygen failed")
    # region BLOCK_publish_authorized_keys Refresh authorized_keys from current pubkey
    pub = (SSH_DIR / "id_ed25519.pub").read_text().strip()
    (SSH_DIR / "authorized_keys").write_text(pub + "\n")
    key.chmod(0o600)
    # endregion BLOCK_publish_authorized_keys
    # list_private_keys() scans keys_dir; keep ONLY the private key there.
    link = KEYS_DIR / "id_ed25519"
    if not link.exists():
        link.symlink_to(key)


# endregion FUNC_ensure_ssh_key


def ensure_sample_engine() -> None:
    d = ENGINES_DIR / "test_shell"
    d.mkdir(parents=True, exist_ok=True)
    run_sh = d / "run.sh"
    if not run_sh.exists():
        run_sh.write_text("#!/bin/sh\nset -eu\nsleep 3\ncat 1.input > 1.input.out\n")
        run_sh.chmod(0o755)


# region FUNC_ensure_config
# PURPOSE: Merge dev defaults into yascheduler.conf so the daemon connects to the dev DB/SSH without clobbering any engines, cloud sections, or overrides the user has added by hand.
# INVARIANTS:
# - Touched keys: [db].host/port/user/password/database, [local].data_dir, [remote].user, and [engine.test_shell] (only if absent).
# - Every other section (user-added engines, cloud providers, jump-host config, concurrency limits) is preserved verbatim.
# RATIONALE:
# - Q: Why set only data_dir under [local] instead of keys_dir/tasks_dir/engines_dir?
#   A: _parse_local_section derives keys_dir/tasks_dir/engines_dir from data_dir via .resolve(), so a single path is enough and avoids drift between four INI keys.
def ensure_config() -> None:
    cp = ConfigParser(interpolation=None)
    cp.read(CONF_PATH)

    # region BLOCK_db_section Overwrite the dev DB connection coordinates
    if not cp.has_section("db"):
        cp["db"] = {}
    cp["db"]["host"] = "localhost"
    cp["db"]["port"] = "15432"
    cp["db"]["user"] = "yascheduler"
    cp["db"]["password"] = "yascheduler"  # noqa: S105
    cp["db"]["database"] = "yascheduler"
    # endregion BLOCK_db_section

    # data_dir is the only path needed — _parse_local_section derives
    # keys_dir/tasks_dir/engines_dir from it via .resolve().
    if not cp.has_section("local"):
        cp["local"] = {}
    cp["local"]["data_dir"] = str(RUN_DIR)

    if not cp.has_section("remote"):
        cp["remote"] = {}
    cp["remote"]["user"] = "testuser"

    if not cp.has_section("clouds"):
        cp.add_section("clouds")

    if not cp.has_section("engine.test_shell"):
        cp["engine.test_shell"] = dict(_TEST_SHELL)

    with CONF_PATH.open("w") as f:
        cp.write(f)
    print(f"Config: {CONF_PATH}")


# endregion FUNC_ensure_config


# region FUNC_ensure_containers
# PURPOSE: Start the postgres and sshd containers idempotently and block until both report healthy so the DB schema can be applied immediately afterwards.
# REQUIRES: SSH keypair + authorized_keys already provisioned by ensure_ssh_key() (the sshd bind-mount reads that file at start).
def ensure_containers() -> None:
    auth_keys = SSH_DIR / "authorized_keys"

    # region BLOCK_start_postgres Recreate the DB container if not running
    if ctr_status(DB_CTR) != "running":
        ctr("rm", "-f", DB_CTR, capture_output=True)
        print("Starting postgres...")
        ctr(
            "run",
            "-d",
            "--name",
            DB_CTR,
            "-e",
            "POSTGRES_USER=yascheduler",
            "-e",
            "POSTGRES_PASSWORD=yascheduler",
            "-e",
            "POSTGRES_DB=yascheduler",
            "-p",
            "15432:5432",
            "-v",
            f"{DB_VOLUME}:/var/lib/postgresql/data",
            "--health-cmd",
            "pg_isready -U yascheduler -d yascheduler",
            "--health-interval",
            "2s",
            "--health-retries",
            "30",
            POSTGRES_IMAGE,
            check=True,
        )
    # endregion BLOCK_start_postgres

    # region BLOCK_start_sshd Recreate the sshd container if not running
    if ctr_status(SSHD_CTR) != "running":
        ctr("rm", "-f", SSHD_CTR, capture_output=True)
        print("Starting sshd...")
        ctr(
            "run",
            "-d",
            "--name",
            SSHD_CTR,
            "-e",
            "SSH_USER=testuser",
            "-e",
            "ALLOWED_IPS=AllowUsers testuser",
            "-p",
            "2222:2222",
            "-v",
            f"{auth_keys}:/authorized_keys:ro",
            "--health-cmd",
            "pgrep -f 'sshd.*-D'",
            "--health-interval",
            "2s",
            "--health-retries",
            "30",
            SSHD_IMAGE,
            check=True,
        )
    # endregion BLOCK_start_sshd

    wait_healthy(DB_CTR, "postgres")
    wait_healthy(SSHD_CTR, "sshd")


# endregion FUNC_ensure_containers


def init_schema() -> None:
    print("Applying DB schema + migrations...")
    uv("yainit", "--schema")


# region FUNC_register_node
# PURPOSE: Register the sshd container as a scheduler node, tolerating the "already in DB" case so dev.py up stays idempotent across re-runs.
# INVARIANTS: A registration failure that is NOT "already in DB" aborts the bootstrap via die().
def register_node() -> None:
    print("Registering sshd node...")
    r = uv(
        "yasetnode",
        "testuser@localhost:2222",
        "--skip-setup",
        capture=True,
        check=False,
    )
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0 and "already in DB" not in r.stdout + r.stderr:
        die(f"yasetnode failed (exit {r.returncode})")


# endregion FUNC_register_node


# region FUNC_bootstrap
# PURPOSE: Orchestrate the full dev sandbox bring-up in dependency order (keys → config → containers → schema → node) so the daemon can be started immediately afterwards.
# REQUIRES: A container runtime (docker or podman) available in PATH — verified by detect_runtime().
def bootstrap() -> None:
    runtime = detect_runtime()
    print(f"Using container runtime: {runtime}")
    ensure_ssh_key()
    ensure_sample_engine()
    ensure_config()
    ensure_containers()
    init_schema()
    register_node()


# endregion FUNC_bootstrap


def containers_healthy() -> bool:
    for name in (DB_CTR, SSHD_CTR):
        r = ctr(
            "inspect",
            "-f",
            "{{.State.Health.Status}}",
            name,
            capture_output=True,
            text=True,
        )
        if r.stdout.strip() != "healthy":
            return False
    return True


# --- commands --------------------------------------------------------------


# region FUNC_cmd_up
# PURPOSE: Entry point for `dev.py up` — bootstrap on cold start, then replace the Python process with the daemon so Ctrl-C flows straight through.
# INVARIANTS: If both containers are already healthy, skips bootstrap and starts the daemon immediately (warm restart).
def cmd_up() -> None:
    if containers_healthy():
        print("Dev environment already up.")
    else:
        bootstrap()
    print("\nStarting daemon (Ctrl-C to stop)...\n")
    os.chdir(ROOT)
    env = dict(os.environ, YASCHEDULER_CONF_PATH=str(CONF_PATH))
    os.execvpe("uv", ["uv", "run", "yascheduler", "-l", "DEBUG"], env)  # noqa: S606


# endregion FUNC_cmd_up


def cmd_down() -> None:
    print("Stopping dev containers...")
    ctr("rm", "-f", DB_CTR, SSHD_CTR, check=False)


def cmd_run(args: list[str]) -> None:
    if not args:
        die("usage: ./dev.py run <tool> [args...]")
    os.chdir(ROOT)
    env = dict(os.environ, YASCHEDULER_CONF_PATH=str(CONF_PATH))
    os.execvpe("uv", ["uv", "run", *args], env)  # noqa: S606


def cmd_reinit() -> None:
    print("Removing containers + DB volume...")
    ctr("rm", "-f", DB_CTR, SSHD_CTR, check=False)
    ctr("volume", "rm", "-f", DB_VOLUME, check=False)
    bootstrap()
    print("DB reinitialized.")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "up":
        cmd_up()
    elif cmd == "down":
        cmd_down()
    elif cmd == "run":
        cmd_run(sys.argv[2:])
    elif cmd == "reinit":
        cmd_reinit()
    else:
        print(__doc__)
        sys.exit(0 if cmd == "help" else 1)


if __name__ == "__main__":
    main()
