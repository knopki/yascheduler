# FILE: tests/e2e/conftest.py
# VERSION: 2.6.0
# START_MODULE_CONTRACT
#   PURPOSE: E2E test fixtures — PostgreSQL + SSH container pool, config, schema, log capture, and UoW-based DB access.
#   SCOPE: Session-scoped containers (postgres + ssh_pool of two), config; function-scoped pg_conn/pg_executor/uow_factory with TRUNCATE, log_records (getMessage() + extra-diff assertions against _NATIVE_KEYS).
#   DEPENDS: M-ENTRYPOINTS-CONFIG, M-SSH-REPOSITORY, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-UOW, M-APPLICATION-MESSAGE-BUS
#   LINKS: M-ENTRYPOINTS-CONFIG, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-UOW, M-APPLICATION-MESSAGE-BUS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   pytest_collection_modifyitems - auto-mark tests as "e2e"
#   postgres_container - session-scoped PostgreSQL container
#   _db_config - session-scoped PostgresDbConfig from container URL
#   ssh_pool - session-scoped list of TWO SSH containers sharing ONE keypair (distinct bridge IPs, port 2222)
#   ssh_container - thin wrapper returning ssh_pool[0] for backward compat with test_consume_retry.py
#   e2e_config - session-scoped Config with temp dir, INI, engine script, single SSH key symlink
#   _init_schema - session-scoped schema.sql application via apply_schema()
#   _bus - session-scoped bare MessageBus for UoW event dispatch
#   pg_executor - function-scoped ThreadPoolExecutor for pg8000
#   pg_conn - function-scoped raw pg8000 connection with TRUNCATE teardown
#   uow_factory - function-scoped factory returning PostgresUnitOfWork instances
#   log_records - function-scoped in-memory LogCaptureHandler attached to the "yascheduler" logger at DEBUG; tests assert via record.getMessage() (former block marker) plus extra-diff {k: getattr(r,k) for k in r.__dict__ if k not in _NATIVE_KEYS}; descendant propagation from yascheduler.* logger names (logging.getLogger(__name__)) still reaches the parent
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.6.0 - switch-to-standard-logging: update log_records fixture docstring to describe getMessage() + extra-diff assertions (former block marker is now the message; structured fields are record attrs beyond _NATIVE_KEYS); descendant propagation from yascheduler.* names via logging.getLogger(__name__) unchanged.
#   PREVIOUS_CHANGE: v2.5.0 - reform-grace-logging slice 8: update log_records fixture docstring to describe structured-field assertions (record.block/record.fields) and propagation from M-ID-namespaced loggers.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import asyncssh
import pg8000.native
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy
from testcontainers.postgres import PostgresContainer

from yascheduler.application import MessageBus
from yascheduler.entrypoints.config_parser import parse_config
from yascheduler.infra.persistence import PostgresDbConfig, apply_migrations
from yascheduler.infra.persistence.postgres_schema import apply_schema
from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from yascheduler.entrypoints import Config


_SSH_IMAGE = "lscr.io/linuxserver/openssh-server:10.2_p1-r0-ls222"
_SSH_USERNAME = "testuser"
_YASCHEDULER_LOGGER = "yascheduler"


def _container_bridge_ip(container: DockerContainer) -> str:
    """Return the container's bridge-network IP address.

    `get_container_host_ip()` returns the docker host (e.g. ``localhost``)
    for every container in the default docker_host connection mode, which
    collapses the two-container pool into a single indistinguishable host.
    The bridge IP is distinct per container and reachable from the host on
    rootful podman/netavark (verified) and on Docker bridge networks.
    """
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    networks: dict[str, dict[str, Any]] = (
        wrapped.attrs.get("NetworkSettings", {}).get("Networks", {}) or {}
    )
    for net in networks.values():
        ip = net.get("IPAddress")
        if ip:
            return str(ip)
    top = wrapped.attrs.get("NetworkSettings", {}).get("IPAddress")
    if top:
        return str(top)
    raise RuntimeError("could not determine container bridge IP")


# START_CONTRACT: LogCaptureHandler
#   PURPOSE: In-memory logging.Handler that appends every LogRecord to a list, for e2e log-grepping.
#   INPUTS: { records: list[logging.LogRecord] - list to append to (supplied by the fixture) }
#   OUTPUTS: { None - mutates records in place via emit }
#   SIDE_EFFECTS: None beyond the records list append.
#   LINKS: log_records fixture (this module)
# END_CONTRACT: LogCaptureHandler
class LogCaptureHandler(logging.Handler):
    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/tests/e2e/" in str(item.path):
            item.add_marker("e2e")


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def _db_config(postgres_container: PostgresContainer) -> PostgresDbConfig:
    url = urlparse(postgres_container.get_connection_url())
    return PostgresDbConfig(
        user=url.username or "test",
        password=url.password or "test",
        database=url.path.lstrip("/"),
        host=url.hostname or "localhost",
        port=url.port or 5432,
    )


@pytest.fixture(scope="session")
async def ssh_pool(
    tmp_path_factory: Any,
) -> AsyncGenerator[list[dict[str, Any]], None]:
    # START_BLOCK_KEYPAIR
    key_dir = tmp_path_factory.mktemp("ssh_keys")
    key_path = key_dir / "id_rsa"
    key = asyncssh.generate_private_key("ssh-rsa")
    public_key_str = key.export_public_key("openssh").decode().strip()
    key.write_private_key(str(key_path))
    # END_BLOCK_KEYPAIR

    # START_BLOCK_START_CONTAINERS
    containers: list[DockerContainer] = []
    try:
        for _ in range(2):
            c = DockerContainer(_SSH_IMAGE)
            c.with_env("USER_NAME", _SSH_USERNAME)
            c.with_env("PUBLIC_KEY", public_key_str)
            c.with_exposed_ports(2222)
            c.waiting_for(LogMessageWaitStrategy("sshd is listening"))
            c.start()
            containers.append(c)

        # Give sshd a moment to accept connections after the log line; the
        # wait strategy only confirms the listener, not a ready socket.
        import asyncio

        await asyncio.sleep(1)

        entries: list[dict[str, Any]] = []
        for c in containers:
            host = _container_bridge_ip(c)
            entries.append(
                {
                    "host": host,
                    "port": 2222,
                    "username": _SSH_USERNAME,
                    "key_path": PurePosixPath(str(key_path)),
                },
            )
        assert entries[0]["host"] != entries[1]["host"], (
            "ssh_pool containers must have distinct bridge IPs; "
            f"got {entries[0]['host']} twice"
        )
        yield entries
    finally:
        for c in containers:
            c.stop()
    # END_BLOCK_START_CONTAINERS


@pytest.fixture(scope="session")
def ssh_container(ssh_pool: list[dict[str, Any]]) -> dict[str, Any]:
    # Backward-compat wrapper for test_consume_retry.py: the single-container
    # fixture is now the first entry of the pool. The pool shares one keypair,
    # so key_path/username are identical to the pre-2.3.0 single-container case.
    return ssh_pool[0]


@pytest.fixture(scope="session")
def e2e_config(
    tmp_path_factory: Any,
    _db_config: PostgresDbConfig,
    ssh_pool: list[dict[str, Any]],
) -> Config:
    # ssh_pool shares one keypair across both containers; index 0 carries the
    # shared username/key_path that the single-container fixture used to provide.
    ssh = ssh_pool[0]
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
        f"user = {ssh['username']}\n"
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
    src = Path(str(ssh["key_path"]))
    dst = keys_dir / src.name
    dst.symlink_to(src)
    # END_BLOCK_SSH_KEY

    # START_BLOCK_ENV_CONFIG
    os.environ["YASCHEDULER_CONF_PATH"] = str(ini_path)
    return parse_config(str(ini_path))
    # END_BLOCK_ENV_CONFIG


@pytest.fixture(scope="session")
def _init_schema(
    _db_config: PostgresDbConfig,
) -> None:
    """Apply schema once per session, then apply pending migrations."""
    apply_schema(_db_config)
    apply_migrations(_db_config)


@pytest.fixture(scope="session")
def _bus() -> MessageBus:
    return MessageBus()


@pytest.fixture
def pg_executor() -> Generator[ThreadPoolExecutor, None, None]:
    executor = ThreadPoolExecutor(max_workers=1)
    yield executor
    executor.shutdown(wait=False)


@pytest.fixture
async def pg_conn(
    _db_config: PostgresDbConfig,
    _init_schema: None,
    pg_executor: ThreadPoolExecutor,
) -> AsyncGenerator[pg8000.native.Connection, None]:
    conn = pg8000.native.Connection(
        user=_db_config.user,
        host=_db_config.host,
        database=_db_config.database,
        port=_db_config.port,
        password=_db_config.password,
    )
    yield conn
    conn.run("TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE")
    conn.close()
    pg_executor.shutdown(wait=False)


@pytest.fixture
def uow_factory(
    _db_config: PostgresDbConfig,
    _init_schema: None,
    _bus: MessageBus,
    pg_conn: pg8000.native.Connection,
) -> Callable[[], PostgresUnitOfWork]:
    def _factory() -> PostgresUnitOfWork:
        return PostgresUnitOfWork(_db_config, _bus)

    return _factory


@pytest.fixture
def log_records() -> Generator[list[logging.LogRecord], None, None]:
    # START_BLOCK_ATTACH_HANDLER
    logger = logging.getLogger(_YASCHEDULER_LOGGER)
    records: list[logging.LogRecord] = []
    handler = LogCaptureHandler(records)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    # END_BLOCK_ATTACH_HANDLER
    try:
        yield records
    finally:
        # START_BLOCK_DETACH_HANDLER
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        # END_BLOCK_DETACH_HANDLER
