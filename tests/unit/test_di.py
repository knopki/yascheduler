# FILE: tests/unit/test_di.py
# VERSION: 2.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for di.py — dependency injection composition root.
#   SCOPE: CLIDeps dataclass, make_cli_deps, make_aiida, make_daemon factories.
#   DEPENDS: M-DI, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-SUBMIT, M-APPLICATION-UOW, M-DB, M-CLOUD-PROVISIONER
#   LINKS: M-DI, M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestCLIDeps - CLIDeps dataclass: constructor, submit
#   TestMakeCliDeps - make_cli_deps factory for CLI dependencies
#   TestMakeAiida - make_aiida stub raises NotImplementedError
#   TestMakeDaemon - make_daemon factory: no DB, AllocationTracker, allocation_lock, active_clouds; active_clouds filter applies on pre-built-clouds path too
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.2.0 - Remove test_query_uses_uow_factory (CLIDeps.query removed in drop-cli-deps-query).
#   PREVIOUS_CHANGE: v2.1.0 - Patch _resolve_adapter → resolve_adapter (public facade); add test_prebuilt_clouds_active_clouds_filter_verifies_adapter_resolution (review-hardening).
# END_CHANGE_SUMMARY

import asyncio
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.adapters.persistence.postgres_uow import PostgresUnitOfWork
from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.config import (
    Config,
    ConfigDb,
    ConfigLocal,
    ConfigRemote,
    EngineRepository,
)
from yascheduler.di import CLIDeps, make_aiida, make_cli_deps, make_daemon
from yascheduler.domain.events import (
    TaskAbandoned,
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)

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
    """CLIDeps dataclass: constructor, submit."""

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


class TestMakeCliDeps:
    """make_cli_deps factory for lightweight CLI dependencies."""

    @pytest.mark.asyncio
    async def test_returns_cli_deps_with_correct_fields(self) -> None:
        """make_cli_deps returns CLIDeps with config-derived engines and remote_tasks_dir."""
        config = create_mock_config()

        with patch("yascheduler.di.aiohttp.ClientSession"):
            deps = make_cli_deps(config)

        assert isinstance(deps, CLIDeps)
        assert deps.engines is config.engines
        assert deps.remote_tasks_dir is config.remote.tasks_dir

    @pytest.mark.asyncio
    async def test_uow_factory_creates_postgres_unit_of_work(self) -> None:
        """uow_factory callable returns a PostgresUnitOfWork initialized with config.db and bus."""
        config = create_mock_config()

        with patch("yascheduler.di.aiohttp.ClientSession"):
            deps = make_cli_deps(config)
        uow = cast("PostgresUnitOfWork", deps.uow_factory())

        assert isinstance(uow, PostgresUnitOfWork)
        assert uow._config is config.db

    @pytest.mark.asyncio
    async def test_no_webhook_handlers_in_cli_mode(self) -> None:
        """CLI mode registers no webhook handlers — bus has empty handler registry."""
        config = create_mock_config()

        with patch("yascheduler.di.aiohttp.ClientSession"):
            deps = make_cli_deps(config)

        # Access the bus via the UoW factory to verify no handlers registered
        uow = cast("PostgresUnitOfWork", deps.uow_factory())
        bus = uow._bus
        for event_type in (
            TaskCreated,
            TaskAllocated,
            TaskCompleted,
            TaskFailed,
            TaskAbandoned,
        ):
            assert event_type not in bus._handlers


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

    @pytest.fixture(autouse=True)
    def _stub_http_session(self) -> Iterator[MagicMock]:
        """Stub aiohttp.ClientSession so no real session is created.

        make_daemon hands the session to Orchestrator, which closes it on
        stop(). These tests mock Orchestrator, so stop() never runs — a real
        session would leak and emit "Unclosed client session" on GC.
        """
        session = MagicMock()
        session.close = AsyncMock()
        with patch("yascheduler.di.aiohttp.ClientSession", return_value=session):
            yield session

    @pytest.mark.asyncio
    async def test_creates_dependencies_no_db(self) -> None:
        """make_daemon returns Orchestrator without creating DB."""
        config = create_mock_config()
        mock_orch_instance = MagicMock()

        with (
            patch("yascheduler.di.resolve_adapter", return_value=None) as mock_resolve,
            patch("yascheduler.di.SSHMachineGateway") as mock_gateway,
            patch(
                "yascheduler.di.Orchestrator", return_value=mock_orch_instance
            ) as mock_orch,
            patch("logging.getLogger") as mock_get_logger,
        ):
            mock_gw = MagicMock()
            mock_gateway.return_value = mock_gw
            resolved_log = MagicMock()
            mock_get_logger.return_value = resolved_log

            result = await make_daemon(config)

        assert result is mock_orch_instance

        mock_get_logger.assert_called_once_with("Orchestrator")
        mock_resolve.assert_not_called()
        mock_gateway.assert_called()
        _call_kwargs = mock_orch.call_args.kwargs
        assert "clouds" in _call_kwargs
        assert _call_kwargs["clouds"] is not None
        assert _call_kwargs["config"] is config
        assert "uow_factory" in _call_kwargs
        assert callable(_call_kwargs["uow_factory"])
        assert _call_kwargs["gateway"] is mock_gw
        assert _call_kwargs["log"] is resolved_log
        # New: allocation_tracker, allocation_lock, active_clouds
        assert "allocation_tracker" in _call_kwargs
        assert isinstance(_call_kwargs["allocation_tracker"], AllocationTracker)
        assert "allocation_lock" in _call_kwargs
        assert isinstance(_call_kwargs["allocation_lock"], asyncio.Lock)
        assert "active_clouds" in _call_kwargs
        assert isinstance(_call_kwargs["active_clouds"], list)
        # Negative: adapters/configs not passed to Orchestrator
        assert "adapters" not in _call_kwargs
        assert "configs" not in _call_kwargs

    @pytest.mark.asyncio
    async def test_uses_provided_clouds(self) -> None:
        """When clouds= keyword is passed, adapter building is skipped."""
        config = create_mock_config()
        custom_clouds = MagicMock()

        with (
            patch("yascheduler.di.resolve_adapter") as mock_resolve,
            patch("yascheduler.di.Orchestrator"),
            patch("logging.getLogger"),
        ):
            await make_daemon(config, clouds=custom_clouds)

        mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_prebuilt_clouds_active_clouds_filter_verifies_adapter_resolution(
        self,
    ) -> None:
        """On the pre-built-clouds path, active_clouds must filter by both max_nodes>0 AND adapter resolved (clouds.configs key) — otherwise _clouds_get_capacity over-counts for unresolved providers (review-hardening)."""
        # Two configured clouds: both max_nodes>0, but only 'hetzner' has a
        # resolved adapter in the pre-built clouds.
        hetzner_cfg = MagicMock(prefix="hetzner", max_nodes=5)
        azure_cfg = MagicMock(prefix="az", max_nodes=3)
        config = create_mock_config()
        config.clouds = [hetzner_cfg, azure_cfg]

        # Pre-built clouds whose configs dict has only 'hetzner' resolved.
        custom_clouds = MagicMock()
        custom_clouds.configs = {"hetzner": hetzner_cfg}

        with (
            patch("yascheduler.di.resolve_adapter") as mock_resolve,
            patch("yascheduler.di.Orchestrator") as mock_orch,
            patch("logging.getLogger"),
        ):
            await make_daemon(config, clouds=custom_clouds)

        # resolve_adapter must NOT be called on the pre-built-clouds path.
        mock_resolve.assert_not_called()
        # active_clouds must exclude 'az' (no resolved adapter) even though
        # its max_nodes > 0.
        orch_kwargs = mock_orch.call_args.kwargs
        active = orch_kwargs["active_clouds"]
        assert [c.prefix for c in active] == ["hetzner"]

    @pytest.mark.asyncio
    async def test_default_logger(self) -> None:
        """When log=None, logging.getLogger('Orchestrator') is called."""
        config = create_mock_config()

        with (
            patch("yascheduler.di.resolve_adapter", return_value=None),
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
            patch("yascheduler.di.resolve_adapter", return_value=None),
            patch("yascheduler.di.Orchestrator"),
            patch("logging.getLogger") as mock_get_logger,
        ):
            await make_daemon(config, log=custom_log)

        mock_get_logger.assert_not_called()

    @pytest.mark.asyncio
    async def test_make_daemon_does_not_import_db(self) -> None:
        """make_daemon must not import or reference DB."""
        import inspect

        import yascheduler.di as di_module

        assert not hasattr(di_module, "DB"), "di.py still imports DB"
        src = inspect.getsource(di_module.make_daemon)
        assert "DB.create" not in src
        assert "node_repo" not in src
