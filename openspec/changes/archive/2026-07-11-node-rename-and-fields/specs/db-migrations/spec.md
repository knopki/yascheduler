## ADDED Requirements

### Requirement: Migration 012 renames ip to hostname and adds node fields

Migration 012 SHALL rename the `ip` column to `hostname` on
`yascheduler_nodes`, widen it to `VARCHAR(255)`, add `created_at`/`updated_at`
with a `BEFORE UPDATE` trigger (mirroring `yascheduler_tasks` migration 007),
add `jump_host`/`jump_port`/`jump_username` placeholder columns, add
`external_id` (backfilled from `hostname` only for rows with a non-empty
`cloud`), create the `NODE_STATUS` enum type with a single label `'OTHER'`
and add the `status` column, and add `NOT NULL` + `CHECK` constraints to the
`port` column.

The migration SHALL perform these steps in order:

1. `ALTER TABLE yascheduler_nodes RENAME COLUMN ip TO hostname`
2. `ALTER TABLE yascheduler_nodes ALTER COLUMN hostname TYPE VARCHAR(255)`
3. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
4. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
5. Create the `YASCHEDULER_TOUCH_UPDATED_AT` trigger function (if not already
   present from migration 007) and install the
   `yascheduler_nodes_touch_updated_at` trigger on `yascheduler_nodes`
6. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS jump_host VARCHAR(255)`
   (nullable)
7. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS jump_port INTEGER NOT NULL DEFAULT 22`
   + `CHECK (jump_port > 0 AND jump_port < 65536)`
8. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS jump_username VARCHAR(255) NOT NULL DEFAULT 'root'`
9. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS external_id VARCHAR(255)`
   (nullable)
10. `UPDATE yascheduler_nodes SET external_id = hostname WHERE cloud IS NOT NULL AND hostname <> ''`
    (backfill only for cloud nodes with a non-empty hostname)
11. `CREATE TYPE NODE_STATUS AS ENUM ('OTHER')` (idempotent via DO block)
12. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS status NODE_STATUS NOT NULL DEFAULT 'OTHER'`
13. `ALTER TABLE yascheduler_nodes ALTER COLUMN port SET NOT NULL`
14. `ALTER TABLE yascheduler_nodes ADD CONSTRAINT node_port_range CHECK (port > 0 AND port < 65536)`

After the migration, `schema.sql` SHALL be updated: the `last_migration`
CONSTANT bumped from `'011'` to `'012'`, and the `yascheduler_nodes`
`CREATE TABLE` snapshot updated to include all new columns.

#### Scenario: Migration 012 renames ip to hostname
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `"011"`
- **THEN** the `ip` column is renamed to `hostname` on `yascheduler_nodes`, widened to `VARCHAR(255)`, and `"012"` is recorded in `yascheduler_migrations`

#### Scenario: Migration 012 adds created_at and updated_at with trigger
- **WHEN** migration 012 runs
- **THEN** `created_at` and `updated_at` columns are added to `yascheduler_nodes` with `DEFAULT NOW()`, and the `yascheduler_nodes_touch_updated_at` trigger is installed

#### Scenario: Migration 012 backfills external_id for cloud nodes only
- **WHEN** migration 012 runs on a database with a cloud node `hostname="10.0.0.1", cloud="aws"` and a static node `hostname="10.0.0.2", cloud=NULL`
- **THEN** the cloud node gets `external_id="10.0.0.1"` and the static node keeps `external_id=NULL`

#### Scenario: Migration 012 creates NODE_STATUS enum and status column
- **WHEN** migration 012 runs
- **THEN** the `NODE_STATUS` enum type is created with label `'OTHER'`, and the `status` column is added with `NOT NULL DEFAULT 'OTHER'`

#### Scenario: Migration 012 adds port constraints
- **WHEN** migration 012 runs
- **THEN** the `port` column gains `NOT NULL` and a `CHECK (port > 0 AND port < 65536)` constraint named `node_port_range`

#### Scenario: Migration 012 adds jump host fields
- **WHEN** migration 012 runs
- **THEN** `jump_host` (VARCHAR(255), nullable), `jump_port` (INTEGER NOT NULL DEFAULT 22, CHECK 0-65535), and `jump_username` (VARCHAR(255) NOT NULL DEFAULT 'root') columns are added

#### Scenario: Schema snapshot updated after migration 012
- **WHEN** the `schema.sql` `CREATE TABLE yascheduler_nodes` is inspected after migration 012
- **THEN** it includes `hostname VARCHAR(255)`, `created_at`/`updated_at`, `jump_host`/`jump_port`/`jump_username`, `external_id`, `status NODE_STATUS`, and the `port` CHECK constraint; the `last_migration` CONSTANT is `'012'`