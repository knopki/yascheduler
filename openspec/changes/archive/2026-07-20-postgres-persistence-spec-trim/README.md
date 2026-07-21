# postgres-persistence-spec-trim

Trim `postgres-persistence` spec to behavioral SHALL statements + Gherkin scenarios; relocate SQL-binding / row-mapping invariants, `SHALL NOT` negative-space enumerations, design rationale, and the schema/migration duplication already owned by `db-migrations` + `postgres-schema-apply` into GRACE markup on `yascheduler/infra/persistence/exceptions.py`, `postgres_uow.py`, `postgres.py`, and `sql_loader.py`.
