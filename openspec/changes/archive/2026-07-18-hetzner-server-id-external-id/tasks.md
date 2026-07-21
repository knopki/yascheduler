## 1. Hetzner external_id uses server ID instead of IP

- [x] 1.1 Update `hetzner_create_node` to store `str(server.id)` as `external_id` instead of the VM's IP address; `hostname` stays the IP
- [x] 1.2 Update `hetzner_delete_node` to resolve via `client.servers.get_by_id(int(external_id))`, wrap `int()` conversion in try/except for stale IP-string values, and remove `find_srv`
- [x] 1.3 Update unit tests in `test_cloud_provider_create_delete.py` for new Hetzner external_id semantics (mock `server.id`, mock `get_by_id` instead of `get_all`)
- [x] 1.4 Update e2e test helpers in `test_hetzner_live.py` (`_assert_vm_deleted`, `_delete_one_best_effort`, `_cleanup_observed`) to use server ID for deletion
