## MODIFIED Requirements

### Requirement: SQL file layout

The system SHALL keep task SQL in versioned `.sql` files under
`infra/persistence/sql/task/` loaded by `load_query(name)` with `@cache`
caching. The system SHALL keep node SQL in versioned `.sql` files under
`infra/persistence/sql/node/` loaded by the same `load_query(name)` cache.

The exhaustive file inventory (the exact `.sql` file names per entity) lives
in the persistence module's `MODULE_CONTRACT` SCOPE — it is shape, not
behavior. The spec keeps only the loading-cache rule and the
schema-vs-migration ownership split.

The schema DDL snapshot and migration file format are owned by the
`postgres-schema-apply` and `db-migrations` capabilities respectively and
are not restated here.

#### Scenario: SQL files loaded via load_query

- **WHEN** a task or node SQL file is requested
- **THEN** the content is returned; subsequent calls return the cached content
