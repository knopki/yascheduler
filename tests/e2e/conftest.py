# FILE: tests/e2e/conftest.py
# VERSION: 2.0.0
# START_MODULE_CONTRACT
#   PURPOSE: E2E test fixtures — PostgreSQL + SSH containers, config, schema, DB.
#   SCOPE: Session-scoped containers and config, function-scoped DB with TRUNCATE.
#   DEPENDS: M-DB, M-CONFIG, M-SSH-GATEWAY
#   LINKS: M-DB, M-CONFIG
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   pytest_collection_modifyitems - auto-mark tests as "e2e"
#   postgres_container - session-scoped PostgreSQL container
#   _db_config - session-scoped ConfigDb from container URL
#   ssh_container - session-scoped SSH container with key pair
#   e2e_config - session-scoped Config with temp dir, INI, engine script, SSH key
#   _init_schema - session-scoped schema.sql application
#   db - function-scoped DB with TRUNCATE teardown
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Add E2E fixtures: postgres, SSH, config, schema, db.
#   PREVIOUS_CHANGE: v1.0.0 - Auto-mark e2e tests via directory-level conftest hook.
# END_CHANGE_SUMMARY

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import asyncssh
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy
from testcontainers.postgres import PostgresContainer

from yascheduler.config import Config
from yascheduler.config.db import ConfigDb
from yascheduler.db import DB

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


def pytest_collection_modifyitems(items) -> None:
    for item in items:
        if "/tests/e2e/" in str(item.path):
            item.add_marker("e2e")


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def _db_config(postgres_container: PostgresContainer) -> ConfigDb:
    url = urlparse(postgres_container.get_connection_url())
    return ConfigDb(
        user=url.username or "test",
        password=url.password or "test",
        database=url.path.lstrip("/"),
        host=url.hostname or "localhost",
        port=url.port or 5432,
    )


@pytest.fixture(scope="session")
async def ssh_container(
    tmp_path_factory: Any,
) -> AsyncGenerator[dict[str, Any], None]:
    import asyncio

    key_dir = tmp_path_factory.mktemp("ssh_keys")
    key_path = key_dir / "id_rsa"

    key = asyncssh.generate_private_key("ssh-rsa")
    public_key_str = key.export_public_key("openssh").decode().strip()
    key.write_private_key(str(key_path))

    container = DockerContainer("lscr.io/linuxserver/openssh-server:10.2_p1-r0-ls222")
    container.with_env("USER_NAME", "testuser")
    container.with_env("PUBLIC_KEY", public_key_str)
    container.with_exposed_ports(2222)
    container.waiting_for(LogMessageWaitStrategy("sshd is listening"))

    container.start()
    try:
        await asyncio.sleep(1)
        host = container.get_container_host_ip()
        if host == "localhost":
            host = "127.0.0.1"
        port = int(container.get_exposed_port(2222))
        yield {
            "host": host,
            "port": port,
            "username": "testuser",
            "key_path": PurePosixPath(str(key_path)),
        }
    finally:
        container.stop()


@pytest.fixture(scope="session")
def e2e_config(
    tmp_path_factory: Any,
    _db_config: ConfigDb,
    ssh_container: dict[str, Any],
) -> Config:
    tmp = tmp_path_factory.mktemp("e2e_config")
    data_dir = tmp / "data"

    ini_path = tmp / "yascheduler.conf"
    db_cfg = _db_config
    ini_content = (
        f"[db]\n"
        f"host = {db_cfg.host}\n"
        f"port = {db_cfg.port}\n"
        f"user = {db_cfg.user}\n"
        f"password = {db_cfg.password}\n"
        f"database = {db_cfg.database}\n"
        f"\n"
        f"[local]\n"
        f"data_dir = {data_dir}\n"
        f"\n"
        f"[remote]\n"
        f"user = {ssh_container['username']}\n"
        f"\n"
        f"[engine.test_shell]\n"
        f"spawn = {{engine_path}}/run.sh\n"
        f"check_pname = sleep\n"
        f"input_files = 1.input\n"
        f"output_files = 1.input.out\n"
        f"deploy_local_files = run.sh\n"
        f"sleep_interval = 1\n"
        f"platforms = linux\n"
    )
    ini_path.write_text(ini_content)

    # START_BLOCK_ENGINE_SCRIPT
    engines_dir = tmp / "data" / "engines" / "test_shell"
    engines_dir.mkdir(parents=True)
    run_sh = engines_dir / "run.sh"
    run_sh.write_text("#!/bin/sh\nsleep 3\ncat 1.input > 1.input.out\n")
    run_sh.chmod(run_sh.stat().st_mode | stat.S_IEXEC)
    # END_BLOCK_ENGINE_SCRIPT

    # START_BLOCK_SSH_KEY
    keys_dir = tmp / "data" / "keys"
    keys_dir.mkdir(parents=True)
    src = Path(str(ssh_container["key_path"]))
    dst = keys_dir / src.name
    dst.symlink_to(src)
    # END_BLOCK_SSH_KEY

    # START_BLOCK_ENV_CONFIG
    os.environ["YASCHEDULER_CONF_PATH"] = str(ini_path)
    config = Config.from_config_parser(str(ini_path))
    # END_BLOCK_ENV_CONFIG

    return config


@pytest.fixture(scope="session")
async def _init_schema(
    postgres_container: PostgresContainer,
    _db_config: ConfigDb,
) -> None:
    instance = await DB.create(_db_config, automigrate=False)
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "yascheduler"
        / "adapters"
        / "persistence"
        / "sql"
        / "schema.sql"
    )
    await instance.run(schema_path.read_text())
    await instance.migrate()
    await instance.close()


@pytest.fixture
async def db(
    _db_config: ConfigDb,
    _init_schema: None,
) -> AsyncGenerator[DB, None]:
    instance = await DB.create(_db_config, automigrate=False)
    yield instance
    await instance.run("TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE")
    await instance.close()
