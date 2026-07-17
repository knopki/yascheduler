## 1. DTO and Protocol Contracts

- [x] 1.1 Create `yascheduler/infra/cloud/dto.py` with `CloudCreateNodeDTO` frozen dataclass (external_id, hostname, username, port, jump_host, jump_port, jump_username)
- [x] 1.2 Update `CreateNodeCallable` protocol in `protocols.py`: return type `str` → `CloudCreateNodeDTO`
- [x] 1.3 Update `DeleteNodeCallable` protocol in `protocols.py`: param `host: str` → `external_id: str`
- [x] 1.4 Export `CloudCreateNodeDTO` from `yascheduler/infra/cloud/__init__.py` facade
- [x] 1.5 Add unit test for `CloudCreateNodeDTO` construction, defaults, and immutability
- [x] 1.6 Update existing protocol/type tests to match new signatures

## 2. Provider Adapter Updates

- [x] 2.1 Update `az_create_node` in `providers/az.py` to return `CloudCreateNodeDTO(external_id=ip, hostname=ip, username=cfg.username, ...)`; rename param `host` → `external_id` in `az_delete_node`
- [x] 2.2 Update `hetzner_create_node` in `providers/hetzner.py` to return DTO; rename param in `hetzner_delete_node`
- [x] 2.3 Update `upcloud_create_node` in `providers/upcloud.py` to return DTO; rename param in `upcloud_delete_node`; fix typo `upcload_delete_node` → `upcloud_delete_node` in function name and all references
- [x] 2.4 Update `vastai_create_node` in `providers/vastai.py` to return DTO; rename param in `vastai_delete_node`
- [x] 2.5 Update `providers/__init__.py` and `adapters.py` for the UpCloud function rename
- [x] 2.6 Update provider-level and e2e tests for new return type and param name

## 3. Provisioner Mapping

- [x] 3.1 Update `CloudProvisionerImpl.allocate()` in `manager.py`: map `CloudCreateNodeDTO` fields to Node via `replace(hostname=dto.hostname, external_id=dto.external_id, ...)`
- [x] 3.2 Update `CloudProvisionerImpl.deallocate()` in `manager.py`: call `adapter.delete_node(cfg=config, external_id=node.external_id)` instead of `host=node.hostname`
- [x] 3.3 Update both setup-failure error paths in `allocate()` to use `external_id` for VM deletion
- [x] 3.4 Remove jump-resolution logic from `_setup_vm()` — `_setup_vm` shall not modify jump_host/jump_port/jump_username
- [x] 3.5 Update provisioner unit tests: mock `create_node` returning `CloudCreateNodeDTO`; assert DTO fields mapped correctly; assert `delete_node` called with `external_id`; assert _setup_vm does not overwrite jump
