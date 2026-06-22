# FILE: tests/unit/test_provider_selection.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for select_provider_pure — pure cloud provider selection.
#   SCOPE: select_provider_pure priority/capacity/platform-support behavior.
#   DEPENDS: M-CLOUD-PROVIDER-SELECTION
#   LINKS: M-CLOUD-PROVIDER-SELECTION
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestSelectProviderPure - Tests for priority, capacity, platform support, edge cases
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial test suite for select_provider_pure (cloud-provisioner-pure).
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from yascheduler.adapters.cloud.adapters import CloudAdapter
from yascheduler.adapters.cloud.provider_selection import select_provider_pure

if TYPE_CHECKING:
    from yascheduler.config.cloud import ConfigCloud


def _make_adapter(name: str, supports_platforms: list[str]) -> CloudAdapter:
    """Build a mock CloudAdapter matching the contract used by select_provider_pure."""
    adapter = MagicMock(spec=CloudAdapter)
    adapter.name = name
    # supported_platform_checks: iterable of callables; each takes a platform str and returns bool
    adapter.supported_platform_checks = [
        lambda p, sp=sp: p == sp for sp in supports_platforms
    ]
    return cast("CloudAdapter", adapter)


def _make_config(max_nodes: int, priority: int, username: str = "root") -> ConfigCloud:
    """Build a mock ConfigCloud with the fields select_provider_pure reads."""
    cfg = MagicMock()
    cfg.max_nodes = max_nodes
    cfg.priority = priority
    cfg.username = username
    return cast("ConfigCloud", cfg)


@pytest.fixture
def log() -> logging.Logger:
    return logging.getLogger("test_provider_selection")


class TestSelectProviderPure:
    def test_higher_priority_wins(self, log: logging.Logger) -> None:
        """When multiple providers have capacity, the highest-priority one wins."""
        adapter_a = _make_adapter("aws", ["linux"])
        adapter_b = _make_adapter("gcp", ["linux"])
        adapters = {"aws": adapter_a, "gcp": adapter_b}
        configs = {
            "aws": _make_config(max_nodes=10, priority=50),
            "gcp": _make_config(max_nodes=10, priority=100),
        }
        result = select_provider_pure(adapters, configs, ["linux"], {}, log)
        assert result is not None
        assert result.name == "gcp"  # higher priority

    def test_full_provider_skipped(self, log: logging.Logger) -> None:
        """When current_counts >= max_nodes, provider excluded."""
        adapter_a = _make_adapter("aws", ["linux"])
        adapters = {"aws": adapter_a}
        configs = {"aws": _make_config(max_nodes=5, priority=100)}
        # aws is full
        result = select_provider_pure(adapters, configs, ["linux"], {"aws": 5}, log)
        assert result is None

    def test_no_platform_support_returns_none(self, log: logging.Logger) -> None:
        """When no provider supports any requested platform, return None."""
        adapter_a = _make_adapter("aws", ["linux"])
        adapters = {"aws": adapter_a}
        configs = {"aws": _make_config(max_nodes=10, priority=100)}
        # Request windows, but aws only supports linux
        result = select_provider_pure(adapters, configs, ["windows"], {"aws": 0}, log)
        assert result is None

    def test_multiple_platforms_any_match(self, log: logging.Logger) -> None:
        """Provider supporting ANY of the requested platforms qualifies."""
        adapter_a = _make_adapter("aws", ["linux", "windows"])
        adapters = {"aws": adapter_a}
        configs = {"aws": _make_config(max_nodes=10, priority=100)}
        # Request both; aws matches linux
        result = select_provider_pure(
            adapters, configs, ["linux", "windows"], {"aws": 0}, log
        )
        assert result is adapter_a

    def test_empty_adapters_returns_none(self, log: logging.Logger) -> None:
        """Empty adapters dict returns None."""
        result = select_provider_pure({}, {}, ["linux"], {}, log)
        assert result is None

    def test_empty_current_counts(self, log: logging.Logger) -> None:
        """Empty current_counts means all providers at zero, full availability."""
        adapter_a = _make_adapter("aws", ["linux"])
        adapters = {"aws": adapter_a}
        configs = {"aws": _make_config(max_nodes=10, priority=100)}
        result = select_provider_pure(adapters, configs, ["linux"], {}, log)
        assert result is adapter_a

    def test_config_none_skipped(self, log: logging.Logger) -> None:
        """Provider with no config entry is skipped (defensive)."""
        adapter_a = _make_adapter("aws", ["linux"])
        adapters = {"aws": adapter_a}
        configs = {}  # no config for aws
        result = select_provider_pure(adapters, configs, ["linux"], {}, log)
        assert result is None

    def test_below_max_partial_capacity(self, log: logging.Logger) -> None:
        """Provider at 3/5 capacity is still selectable."""
        adapter_a = _make_adapter("aws", ["linux"])
        adapters = {"aws": adapter_a}
        configs = {"aws": _make_config(max_nodes=5, priority=100)}
        result = select_provider_pure(adapters, configs, ["linux"], {"aws": 3}, log)
        assert result is adapter_a
