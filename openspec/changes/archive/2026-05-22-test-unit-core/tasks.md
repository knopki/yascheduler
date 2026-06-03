## 1. Data Model Tests

- [x] 1.1 Create `tests/unit/test_models.py` with tests for `TaskStatus` enum values and int subclass check
- [x] 1.2 Add tests for `TaskModel` construction, `TaskStatus` converter, immutability, and hash determinism
- [x] 1.3 Add tests for `NodeModel` construction with defaults and full args

## 2. Config Parsing Tests — Sub-Modules

- [x] 2.1 Create `tests/unit/test_config.py` with tests for `ConfigDb.from_config_parser_section` (overrides and defaults)
- [x] 2.2 Add tests for `ConfigLocal.from_config_parser_section` (path resolution, numeric defaults)
- [x] 2.3 Add tests for `ConfigRemote.from_config_parser_section` (with/without jump host)
- [x] 2.4 Add tests for cloud configs: `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudAzure` (parsing and `AzureImageReference` URN parsing/validation)
- [x] 2.5 Add tests for `Engine.from_config_parser_section` (valid engine, spawn validation, check methods validation, empty input_files)
- [x] 2.6 Add tests for `EngineRepository` (filter, filter_platforms, immutability)
- [x] 2.7 Add tests for `warn_unknown_fields` emitting `ConfigWarning`
## 3. Config Parsing Tests — Top-Level Assembly

- [x] 3.1 Add tests for `Config.from_config_parser` with full INI and with empty sections

## 4. DB Unit Tests with Mocked Connection

- [x] 4.1 Create `tests/unit/test_db.py` with a mock `DB` fixture (mocked `pg8000.Connection`, mock loop, mock executor)
- [x] 4.2 Add tests for node CRUD: `add_node`, `get_node` (found/not found), `get_all_nodes`, `enable_node`, `disable_node`, `remove_node`
- [x] 4.3 Add tests for task CRUD: `add_task`, `get_task`, `update_task_status`, `set_task_running`, `set_task_done`, `set_task_error` (with and without error message)

## 5. FakeDB Helper

- [x] 5.1 Create `tests/fixtures/fake_db.py` with `FakeDB` class implementing node/task CRUD in memory, returning real `TaskModel`/`NodeModel`, auto-incrementing `task_id`
- [x] 5.2 Add tests for `FakeDB` itself (add_task + get_task, add_node + get_all_nodes, status transitions)
