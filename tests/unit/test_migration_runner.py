# FILE: tests/unit/test_migration_runner.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for the migration runner helpers and migration-directory invariants.
#   SCOPE: _prefix_id, _pending, _scan_migrations, _one_migration_subclass; prefix_id uniqueness and last_migration CONSTANT drift guard.
#   DEPENDS: M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-MIGRATION-BASE
#   LINKS: M-PERSISTENCE-MIGRATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_prefix_id_extracts_token_before_first_underscore - _prefix_id returns the token before the first '_'
#   test_pending_returns_all_when_last_is_none - _pending(None, files) returns all files in order
#   test_pending_filters_greater_than_last - _pending keeps only prefix_id > last
#   test_scan_migrations_sorts_by_filename - _scan_migrations globs *.sql+*.py sorted by name
#   test_one_migration_subclass_* - discover exactly one/zero/two Migration subclass(es)
#   test_prefix_id_uniqueness_across_migrations - real migrations/ has unique prefix_ids
#   test_schema_sql_last_migration_constant_matches_latest_migration - schema.sql CONSTANT matches max prefix_id
#   test_schema_sql_uses_identity_not_serial - schema.sql uses GENERATED ALWAYS AS IDENTITY, not SERIAL PRIMARY KEY
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - serial-to-generated-identity: add test_schema_sql_uses_identity_not_serial guarding identity-column DDL in schema.sql.
#   PREVIOUS_CHANGE: v1.0.0 - Initial unit tests for the migration runner (add-db-migrations).
# END_CHANGE_SUMMARY

"""Unit tests for the migration runner (yascheduler.infra.persistence.postgres_migrations).

Covers the pure helpers (_prefix_id, _pending, _scan_migrations,
_one_migration_subclass) and two whole-repository invariants that the runner
does NOT enforce itself: prefix_id uniqueness across migrations/ and the
schema.sql last_migration CONSTANT matching the latest migration's prefix_id.
"""

from __future__ import annotations

import re
import types
from pathlib import Path

import pytest

from yascheduler.infra.persistence.migration_base import Migration
from yascheduler.infra.persistence.postgres_migrations import (
    _MIGRATIONS_DIR,
    _one_migration_subclass,
    _pending,
    _prefix_id,
    _scan_migrations,
)

pytestmark = pytest.mark.unit


# START_CONTRACT: test_prefix_id_extracts_token_before_first_underscore
#   PURPOSE: Verify _prefix_id returns the token before the first underscore.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_prefix_id_extracts_token_before_first_underscore
@pytest.mark.parametrize(
    "filename,expected",
    [
        (Path("001_add_username_port.sql"), "001"),
        (Path("20260701120000_add_index.sql"), "20260701120000"),
        (Path("010_backfill.py"), "010"),
    ],
)
def test_prefix_id_extracts_token_before_first_underscore(
    filename: Path,
    expected: str,
) -> None:
    assert _prefix_id(filename) == expected


# START_CONTRACT: test_pending_returns_all_when_last_is_none
#   PURPOSE: _pending(None, files) returns every file in the input order.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_pending_returns_all_when_last_is_none
def test_pending_returns_all_when_last_is_none() -> None:
    files = [Path("001_a.sql"), Path("002_b.sql")]
    assert _pending(None, files) == files


# START_CONTRACT: test_pending_filters_greater_than_last
#   PURPOSE: _pending keeps only files whose prefix_id > last, preserving sorted order.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_pending_filters_greater_than_last
def test_pending_filters_greater_than_last() -> None:
    files = [Path("001_a.sql"), Path("002_b.sql"), Path("010_c.sql")]
    assert _pending("001", files) == [Path("002_b.sql"), Path("010_c.sql")]


# START_CONTRACT: test_scan_migrations_sorts_by_filename
#   PURPOSE: _scan_migrations globs *.sql and *.py from _MIGRATIONS_DIR and returns them sorted by filename.
#   INPUTS: { tmp_path: Path - temp dir substituted for _MIGRATIONS_DIR via monkeypatch }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None — reads the temp dir only
#   LINKS: M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_scan_migrations_sorts_by_filename
def test_scan_migrations_sorts_by_filename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # START_BLOCK_SETUP_TEMP_DIR
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "010_c.sql").write_text("-- c")
    (migrations_dir / "001_a.sql").write_text("-- a")
    (migrations_dir / "002_b.py").write_text("# b")
    monkeypatch.setattr(
        "yascheduler.infra.persistence.postgres_migrations._MIGRATIONS_DIR",
        migrations_dir,
    )
    # END_BLOCK_SETUP_TEMP_DIR

    result = _scan_migrations()

    assert [p.name for p in result] == ["001_a.sql", "002_b.py", "010_c.sql"]


def _make_module(name: str, body: str) -> types.ModuleType:
    """Build a module whose defined classes carry __module__ == name."""
    mod = types.ModuleType(name)
    mod.__file__ = name
    exec(compile(body, name, "exec"), mod.__dict__)
    return mod


_ONE = (
    "from yascheduler.infra.persistence.migration_base import Migration\n"
    "class A(Migration):\n"
    "    def migrate(self) -> None: ...\n"
)
_ZERO = "from yascheduler.infra.persistence.migration_base import Migration\nx = 1\n"
_TWO = (
    "from yascheduler.infra.persistence.migration_base import Migration\n"
    "class A(Migration):\n"
    "    def migrate(self) -> None: ...\n"
    "class B(Migration):\n"
    "    def migrate(self) -> None: ...\n"
)


def test_one_migration_subclass_finds_exactly_one() -> None:
    mod = _make_module("tmp_one", _ONE)
    klass = _one_migration_subclass(mod)
    assert klass.__name__ == "A"
    assert issubclass(klass, Migration)


def test_one_migration_subclass_zero_raises() -> None:
    mod = _make_module("tmp_zero", _ZERO)
    with pytest.raises(RuntimeError, match="exactly one Migration subclass"):
        _one_migration_subclass(mod)


def test_one_migration_subclass_two_raises() -> None:
    mod = _make_module("tmp_two", _TWO)
    with pytest.raises(RuntimeError, match="exactly one Migration subclass"):
        _one_migration_subclass(mod)


# START_CONTRACT: test_prefix_id_uniqueness_across_migrations
#   PURPOSE: Guard that no two migration files in the real migrations/ dir share a prefix_id. This invariant is the unit test's job, not the runner's.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None — reads migrations/ only
#   LINKS: M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_prefix_id_uniqueness_across_migrations
def test_prefix_id_uniqueness_across_migrations() -> None:
    files = sorted(p.name for p in _MIGRATIONS_DIR.glob("*") if p.is_file())
    assert files, "migrations/ must contain at least one migration file"
    ids = [_prefix_id(Path(name)) for name in files]
    dupes = {pid for pid in ids if ids.count(pid) > 1}
    assert not dupes, f"duplicate prefix_id(s) across migrations/: {dupes}"


# START_CONTRACT: test_schema_sql_last_migration_constant_matches_latest_migration
#   PURPOSE: Catch "forgot step 2" drift — the schema.sql last_migration CONSTANT MUST equal the max prefix_id across migrations/.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None — reads schema.sql and migrations/ only
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_schema_sql_last_migration_constant_matches_latest_migration
def test_schema_sql_last_migration_constant_matches_latest_migration() -> None:
    schema_text = (_MIGRATIONS_DIR.parent / "schema.sql").read_text()
    match = re.search(r"last_migration\s+CONSTANT\s+TEXT\s+:=\s*'([^']+)'", schema_text)
    assert match, "schema.sql must declare last_migration CONSTANT TEXT := '<id>'"
    constant = match.group(1)

    files = [p for p in _MIGRATIONS_DIR.glob("*") if p.is_file()]
    assert files, "migrations/ must contain at least one migration file"
    latest = max(_prefix_id(p) for p in files)

    assert constant == latest, (
        f"schema.sql last_migration CONSTANT '{constant}' does not match "
        f"the latest migration prefix_id '{latest}' (forgot edit step 2?)"
    )


# START_CONTRACT: test_schema_sql_uses_identity_not_serial
#   PURPOSE: Guard that schema.sql declares both PKs as GENERATED ALWAYS AS IDENTITY and never as SERIAL PRIMARY KEY.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None — reads schema.sql only
#   LINKS: M-PERSISTENCE-SCHEMA
# END_CONTRACT: test_schema_sql_uses_identity_not_serial
def test_schema_sql_uses_identity_not_serial() -> None:
    schema_text = (_MIGRATIONS_DIR.parent / "schema.sql").read_text()
    assert "GENERATED ALWAYS AS IDENTITY" in schema_text
    assert "SERIAL PRIMARY KEY" not in schema_text
