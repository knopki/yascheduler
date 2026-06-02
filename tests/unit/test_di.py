# FILE: tests/unit/test_di.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for di.py — dependency injection composition root.
#   SCOPE: CLIDeps dataclass, make_cli_deps, make_aiida, make_daemon factories.
#   DEPENDS: M-DI, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-SUBMIT, M-APPLICATION-UOW, M-DB, M-CLOUD-MANAGER
#   LINKS: M-DI, M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestCLIDeps - CLIDeps dataclass: constructor, submit, query
#   TestMakeCliDeps - make_cli_deps factory for CLI dependencies
#   TestMakeAiida - make_aiida stub raises NotImplementedError
#   TestMakeDaemon - make_daemon factory: default deps, overrides, logging
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Create unit tests for di.py
# END_CHANGE_SUMMARY

from pathlib import Path, PurePosixPath
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.adapters.persistence.postgres_uow import PostgresUnitOfWork
from yascheduler.config import (
    Config,
    ConfigDb,
    ConfigLocal,
    ConfigRemote,
    EngineRepository,
)
from yascheduler.di import CLIDeps, make_aiida, make_cli_deps, make_daemon

# =============================================================================
# Helpers
# =============================================================================


def create_mock_config() -> MagicMock:
    """Create a mocked Config with sub-config mocks needed by DI factories."""
    engines = MagicMock(spec=EngineRepository)
    db = MagicMock(spec=ConfigDb)
    remote = MagicMock(spec=ConfigRemote)
    remote.tasks_dir = PurePosixPath("/tmp/tasks")
    local = MagicMock(spec=ConfigLocal)
    local.tasks_dir = Path("/tmp")

    config = MagicMock(spec=Config)
    config.engines = engines
    config.db = db
    config.remote = remote
    config.clouds = []
    config.local = local
    return config


# =============================================================================
# Tests
# =============================================================================


class TestCLIDeps:
    """CLIDeps dataclass: constructor, submit, query."""

    def test_constructor_stores_fields(self) -> None:
        """CLIDeps stores engines, uow_factory, remote_tasks_dir."""
        engines = MagicMock(spec=EngineRepository)
        uow_factory = MagicMock()
        remote_tasks_dir = PurePosixPath("/tmp/tasks")

        deps = CLIDeps(
            engines=engines,
            uow_factory=uow_factory,
            remote_tasks_dir=remote_tasks_dir,
        )

        assert deps.engines is engines
        assert deps.uow_factory is uow_factory
        assert deps.remote_tasks_dir is remote_tasks_dir

    @pytest.mark.asyncio
    async def test_submit_delegates_to_submit_task(self) -> None:
        """submit() delegates to submit_task with all positional args."""
        engines = MagicMock(spec=EngineRepository)
        uow_factory = MagicMock()
        remote_tasks_dir = PurePosixPath("/tmp/tasks")
        deps = CLIDeps(
            engines=engines,
            uow_factory=uow_factory,
            remote_tasks_dir=remote_tasks_dir,
        )

        with patch(
            "yascheduler.di.submit_task", new=AsyncMock(return_value=42)
        ) as mock_submit:
            result = await deps.submit("my-label", {"key": "val"}, "g09")

        assert result == 42
        mock_submit.assert_awaited_once_with(
            "my-label",
            {"key": "val"},
            "g09",
            engines,
            uow_factory,
            remote_tasks_dir,
        )

    @pytest.mark.asyncio
    async def test_query_uses_uow_factory(self) -> None:
        """query() enters a UoW via uow_factory and calls tasks.get(task_id)."""
        mock_task = MagicMock()
        mock_uow = AsyncMock()
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        mock_uow.tasks.get = AsyncMock(return_value=mock_task)
        uow_factory = MagicMock(return_value=mock_uow)

        deps = CLIDeps(
            engines=MagicMock(),
            uow_factory=uow_factory,
            remote_tasks_dir=PurePosixPath("/tmp/tasks"),
        )

        result = await deps.query(99)

        assert result is mock_task
        uow_factory.assert_called_once_with()
        mock_uow.tasks.get.assert_awaited_once_with(99)


class TestMakeCliDeps:
    """make_cli_deps factory for lightweight CLI dependencies."""

    def test_returns_cli_deps_with_correct_fields(self) -> None:
        """make_cli_deps returns CLIDeps with config-derived engines and remote_tasks_dir."""
        config = create_mock_config()

        deps = make_cli_deps(config)

        assert isinstance(deps, CLIDeps)
        assert deps.engines is config.engines
        assert deps.remote_tasks_dir is config.remote.tasks_dir

    def test_uow_factory_creates_postgres_unit_of_work(self) -> None:
        """uow_factory callable returns a PostgresUnitOfWork initialized with config.db."""
        config = create_mock_config()

        deps = make_cli_deps(config)
        uow = cast("PostgresUnitOfWork", deps.uow_factory())

        assert isinstance(uow, PostgresUnitOfWork)
        assert uow._config is config.db


class TestMakeAiida:
    """make_aiida stub — raises NotImplementedError."""

    def test_raises_not_implemented_error(self) -> None:
        """make_aiida raises NotImplementedError with expected message."""
        config = create_mock_config()

        with pytest.raises(
            NotImplementedError,
            match="make_aiida will be implemented in a future phase",
        ):
            make_aiida(config)


class TestMakeDaemon:
    """make_daemon async factory — creates full daemon dependency graph."""

    @pytest.mark.asyncio
    async def test_creates_all_dependencies_and_returns_orchestrator(self) -> None:
        """make_daemon calls DB.create, builds CloudProvisionerImpl, and returns Orchestrator."""
        config = create_mock_config()
        mock_orch_instance = MagicMock()

        with (
            patch("yascheduler.di.DB.create", new=AsyncMock()) as mock_db_create,
            patch("yascheduler.di._resolve_adapter", return_value=None) as mock_resolve,
            patch("yascheduler.di.SSHMachineGateway") as mock_gateway,
            patch("yascheduler.di.RemoteMachineRepository") as mock_rm_repo,
            patch(
                "yascheduler.di.Orchestrator", return_value=mock_orch_instance
            ) as mock_orch,
            patch("logging.getLogger") as mock_get_logger,
        ):
            mock_db = AsyncMock()
            mock_db_create.return_value = mock_db
            mock_gw = MagicMock()
            mock_gateway.return_value = mock_gw
            mock_rm = MagicMock()
            mock_rm_repo.return_value = mock_rm
            resolved_log = MagicMock()
            mock_get_logger.return_value = resolved_log

            result = await make_daemon(config)

        assert result is mock_orch_instance

        mock_get_logger.assert_called_once_with("Orchestrator")
        mock_db_create.assert_awaited_once_with(config.db)
        # No cloud adapters configured (mock returns None)
        mock_resolve.assert_not_called()
        mock_gateway.assert_called()
        mock_rm_repo.assert_called_once_with(log=resolved_log)
        # Orchestrator receives a CloudProvisionerImpl
        _call_kwargs = mock_orch.call_args.kwargs
        assert "clouds" in _call_kwargs
        assert _call_kwargs["clouds"] is not None
        assert _call_kwargs["config"] is config
        assert "uow_factory" in _call_kwargs
        assert callable(_call_kwargs["uow_factory"])
        assert _call_kwargs["remote_machines"] is mock_rm
        assert _call_kwargs["gateway"] is mock_gw
        assert _call_kwargs["log"] is resolved_log

    @pytest.mark.asyncio
    async def test_uses_provided_db(self) -> None:
        """When db= keyword is passed, DB.create is not called."""
        config = create_mock_config()
        custom_db = AsyncMock()

        with (
            patch("yascheduler.di.DB.create", new=AsyncMock()) as mock_db_create,
            patch("yascheduler.di._resolve_adapter", return_value=None),
            patch("yascheduler.di.RemoteMachineRepository"),
            patch("yascheduler.di.Orchestrator"),
            patch("logging.getLogger"),
        ):
            await make_daemon(config, db=custom_db)

        mock_db_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_provided_clouds(self) -> None:
        """When clouds= keyword is passed, adapter building is skipped."""
        config = create_mock_config()
        custom_clouds = AsyncMock()

        with (
            patch("yascheduler.di.DB.create", new=AsyncMock()) as mock_db_create,
            patch("yascheduler.di._resolve_adapter") as mock_resolve,
            patch("yascheduler.di.RemoteMachineRepository"),
            patch("yascheduler.di.Orchestrator"),
            patch("logging.getLogger"),
        ):
            mock_db_create.return_value = AsyncMock()

            await make_daemon(config, clouds=custom_clouds)

        mock_resolve.assert_not_called()
        mock_db_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_default_logger(self) -> None:
        """When log=None, logging.getLogger('Orchestrator') is called."""
        config = create_mock_config()

        with (
            patch("yascheduler.di.DB.create", new=AsyncMock()),
            patch("yascheduler.di._resolve_adapter", return_value=None),
            patch("yascheduler.di.RemoteMachineRepository"),
            patch("yascheduler.di.Orchestrator"),
            patch("logging.getLogger") as mock_get_logger,
        ):
            await make_daemon(config)

        mock_get_logger.assert_called_once_with("Orchestrator")

    @pytest.mark.asyncio
    async def test_custom_logger_skips_get_logger(self) -> None:
        """When log= is passed, logging.getLogger is not called and the custom logger is used."""
        config = create_mock_config()
        custom_log = MagicMock()

        with (
            patch("yascheduler.di.DB.create", new=AsyncMock()),
            patch("yascheduler.di._resolve_adapter", return_value=None),
            patch("yascheduler.di.RemoteMachineRepository"),
            patch("yascheduler.di.Orchestrator"),
            patch("logging.getLogger") as mock_get_logger,
        ):
            await make_daemon(config, log=custom_log)

        mock_get_logger.assert_not_called()
