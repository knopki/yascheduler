# FILE: tests/unit/test_remote_machine.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for RemoteMachineMetadata state transitions, RemoteMachineRepository.filter, and RemoteMachineAdapter structure.
#   SCOPE: TestRemoteMachineMetadata (initial state, busy transitions, is_free_longer_than), TestRemoteMachineRepositoryFilter (busy, platforms, free_since_gt, reverse_sort, immutability), TestRemoteMachineAdapter (platform names, checks inheritance, callable fields).
#   DEPENDS: M-REMOTE, M-REMOTE-REPO, M-REMOTE-ADAPTERS
#   LINKS: M-REMOTE, M-REMOTE-REPO, M-REMOTE-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestRemoteMachineMetadata - Tests for RemoteMachineMetadata state transitions and is_free_longer_than
#   TestRemoteMachineRepositoryFilter - Tests for RemoteMachineRepository.filter parameter combinations
#   TestRemoteMachineAdapter - Tests for adapter platform names, checks chain, callable fields
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial unit tests for RemoteMachineMetadata, Repository, and Adapter.
# END_CHANGE_SUMMARY
#

from datetime import datetime, timedelta
from unittest.mock import Mock

from yascheduler.remote_machine.remote_machine import (
    RemoteMachine,
    RemoteMachineMetadata,
)
from yascheduler.remote_machine.remote_machine_repository import RemoteMachineRepository
from yascheduler.remote_machine.adapters import (
    linux_adapter,
    debian_adapter,
    debian_like_adapter,
    darwin_adapter,
    windows_adapter,
)
from tests.fixtures.mock_remote_machine import make_mock_remote_machine


class _ComparableMock(Mock):
    """Mock subclass that sorts by meta.free_since via __lt__."""

    def __lt__(self, other):
        fs_self = self.meta.free_since
        fs_other = other.meta.free_since
        if fs_self is None and fs_other is None:
            return False
        if fs_self is None:
            return True
        if fs_other is None:
            return False
        return fs_self < fs_other


def _make_machine(ip, platforms, busy, free_since=None):
    """Helper: create a comparable mock machine with sortable __lt__."""
    base = make_mock_remote_machine(ip=ip, platforms=platforms, busy=busy)
    if free_since is not None:
        base.meta.free_since = free_since
    mock = _ComparableMock(spec=RemoteMachine)
    mock.meta = base.meta
    mock.platforms = base.platforms
    mock.hostname = base.hostname
    return mock


class TestRemoteMachineMetadata:
    """Tests for RemoteMachineMetadata state transitions and is_free_longer_than."""

    def test_initial_state(self):
        """Initial state: busy=None, free_since set to recent datetime."""
        meta = RemoteMachineMetadata()
        assert meta.busy is None
        assert meta.free_since is not None
        delta = datetime.now() - meta.free_since
        assert delta.total_seconds() < 1

    def test_busy_true_sets_free_since_none(self):
        """Setting busy=True sets free_since to None."""
        meta = RemoteMachineMetadata()
        meta.busy = True
        assert meta.busy is True
        assert meta.free_since is None

    def test_busy_false_sets_free_since_recent(self):
        """Setting busy=False sets free_since to recent datetime."""
        meta = RemoteMachineMetadata()
        meta.busy = True
        meta.busy = False
        assert meta.busy is False
        assert meta.free_since is not None
        delta = datetime.now() - meta.free_since
        assert delta.total_seconds() < 1

    def test_is_free_longer_than_when_free(self):
        """is_free_longer_than returns True when free and delta is small."""
        meta = RemoteMachineMetadata()
        meta.busy = False
        assert meta.is_free_longer_than(timedelta(seconds=0)) is True

    def test_is_free_longer_than_when_busy(self):
        """is_free_longer_than returns False when busy."""
        meta = RemoteMachineMetadata()
        meta.busy = True
        assert meta.is_free_longer_than(timedelta(seconds=0)) is False

    def test_is_free_longer_than_not_long_enough(self):
        """is_free_longer_than returns False when not free long enough."""
        meta = RemoteMachineMetadata()
        meta.busy = False
        assert meta.is_free_longer_than(timedelta(days=365)) is False


class TestRemoteMachineRepositoryFilter:
    """Tests for RemoteMachineRepository.filter method."""

    def _make_repo(self, machines):
        """Helper: create repository from list of (ip, platforms, busy) tuples."""
        repo = RemoteMachineRepository(log=None)
        for ip, platforms, busy in machines:
            repo.data[ip] = _make_machine(ip, platforms, busy)
        return repo

    def test_filter_busy_true(self):
        """filter(busy=True) returns only busy machines."""
        repo = self._make_repo(
            [
                ("10.0.0.1", ["linux"], True),
                ("10.0.0.2", ["linux"], False),
            ]
        )
        result = repo.filter(busy=True)
        assert len(result) == 1
        assert "10.0.0.1" in result

    def test_filter_busy_false(self):
        """filter(busy=False) returns only free machines."""
        repo = self._make_repo(
            [
                ("10.0.0.1", ["linux"], True),
                ("10.0.0.2", ["linux"], False),
            ]
        )
        result = repo.filter(busy=False)
        assert len(result) == 1
        assert "10.0.0.2" in result

    def test_filter_platforms_match(self):
        """filter(platforms=['debian']) includes machines with debian platform."""
        repo = self._make_repo(
            [
                ("10.0.0.1", ["linux", "debian"], False),
                ("10.0.0.2", ["linux"], False),
            ]
        )
        result = repo.filter(platforms=["debian"])
        assert len(result) == 1
        assert "10.0.0.1" in result

    def test_filter_platforms_no_match(self):
        """filter(platforms=['windows']) excludes linux-only machines."""
        repo = self._make_repo(
            [
                ("10.0.0.1", ["linux"], False),
            ]
        )
        result = repo.filter(platforms=["windows"])
        assert len(result) == 0

    def test_filter_free_since_gt(self):
        """filter(free_since_gt=delta) includes machines free longer than delta."""
        free_long = datetime.now() - timedelta(minutes=10)
        free_short = datetime.now() - timedelta(seconds=30)

        repo = RemoteMachineRepository(log=None)
        m1 = _make_machine("10.0.0.1", ["linux"], False, free_since=free_long)
        m2 = _make_machine("10.0.0.2", ["linux"], False, free_since=free_short)
        repo.data["10.0.0.1"] = m1
        repo.data["10.0.0.2"] = m2

        result = repo.filter(free_since_gt=timedelta(minutes=5))
        # m1 free for 10min > 5min -> True; m2 free for 30s > 5min -> False
        assert len(result) == 1
        assert "10.0.0.1" in result

    def test_filter_reverse_sort(self):
        """filter(reverse_sort=True) sorts by free_since descending."""
        t1 = datetime.now() - timedelta(minutes=5)
        t2 = datetime.now() - timedelta(minutes=1)

        repo = RemoteMachineRepository(log=None)
        m1 = _make_machine("10.0.0.1", ["linux"], False, free_since=t1)
        m2 = _make_machine("10.0.0.2", ["linux"], False, free_since=t2)
        repo.data["10.0.0.1"] = m1
        repo.data["10.0.0.2"] = m2

        result = repo.filter(reverse_sort=True)
        ips = list(result.keys())
        assert ips == ["10.0.0.2", "10.0.0.1"]

    def test_filter_original_unchanged(self):
        """filter returns new instance without modifying original."""
        repo = self._make_repo(
            [
                ("10.0.0.1", ["linux"], True),
                ("10.0.0.2", ["linux"], False),
            ]
        )
        original_count = len(repo)
        result = repo.filter(busy=False)
        assert len(result) == 1
        assert len(repo) == original_count


class TestRemoteMachineAdapter:
    """Tests for RemoteMachineAdapter structure."""

    def test_linux_adapter_platform(self):
        """linux_adapter has correct platform name."""
        assert linux_adapter.platform == "linux"
        assert linux_adapter.path is not None
        assert linux_adapter.quote is not None
        assert linux_adapter.run is not None
        assert linux_adapter.run_bg is not None
        assert linux_adapter.get_cpu_cores is not None
        assert linux_adapter.list_processes is not None
        assert linux_adapter.pgrep is not None
        assert linux_adapter.setup_node is not None

    def test_debian_adapter_platform(self):
        """debian_adapter has correct platform name."""
        assert debian_adapter.platform == "debian"

    def test_debian_like_adapter_platform(self):
        """debian_like_adapter has correct platform name."""
        assert debian_like_adapter.platform == "debian-like"

    def test_darwin_adapter_platform(self):
        """darwin_adapter has correct platform name."""
        assert darwin_adapter.platform == "darwin"

    def test_windows_adapter_platform(self):
        """windows_adapter has correct platform name."""
        assert windows_adapter.platform == "windows"

    def test_adapter_chain_debian_superset(self):
        """debian_adapter.checks is superset of debian_like_adapter.checks."""
        assert set(debian_adapter.checks) >= set(debian_like_adapter.checks)
        assert len(debian_adapter.checks) > len(debian_like_adapter.checks)

    def test_all_callable_fields_non_none_linux(self):
        """All callable fields on linux_adapter are not None."""
        for attr_name in [
            "quote",
            "run",
            "run_bg",
            "get_cpu_cores",
            "list_processes",
            "pgrep",
            "setup_node",
        ]:
            assert getattr(linux_adapter, attr_name) is not None, (
                f"{attr_name} should not be None"
            )
