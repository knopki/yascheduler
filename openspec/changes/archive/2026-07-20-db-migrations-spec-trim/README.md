# db-migrations-spec-trim

Trim the `db-migrations` spec to requirements-only; relocate design rationale, the `begin()` / `commit()` pattern narrative, the pg8000 autocommit and transient-retry rationale, the `prefix_id`-uniqueness layering note, the migration-edit consequence prose, and the `SHALL NOT` negative-space language on the forward-only requirement into GRACE markup on `yascheduler/infra/persistence/migration_base.py` and `yascheduler/infra/persistence/postgres_migrations.py`. Also wrap the previously-unwrapped `FUNC__rollback` (its inner `BLOCK_rollback` becomes correctly nested).
