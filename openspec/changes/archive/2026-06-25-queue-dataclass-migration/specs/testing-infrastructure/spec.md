## MODIFIED Requirements

### Requirement: UniqueQueue unit tests
Tests for `UniqueQueue` SHALL cover: put/get, deduplication, item_done
tracking (allows re-queueing after done), and `task_done` raising
`NotImplementedError`.

Deduplication in `UniqueQueue` SHALL be keyed on the message `id`. Two
`UMessage` instances with equal `id` SHALL be treated as duplicates regardless
of their `payload`. The `payload` field SHALL NOT participate in `__eq__` or
`__hash__`; therefore an unhashable `payload` (e.g. a `dict`) SHALL be
accepted at construction and during enqueue/get/item_done operations.

#### Scenario: Duplicate message is skipped
- **WHEN** two `UMessage` instances with the same `id` are put into a `UniqueQueue`
- **THEN** only one message is in the queue

#### Scenario: Different payloads with the same id are deduplicated
- **WHEN** `UMessage(id="a", payload="x")` and `UMessage(id="a", payload="y")` (same id, different payloads) are both put into a `UniqueQueue`
- **THEN** the queue size is 1, and the retained message is the first one inserted (payload `"x"`)

#### Scenario: Unhashable payload is accepted
- **WHEN** a `UMessage` is constructed with an unhashable payload (e.g. a `dict`) and put into a `UniqueQueue`, then consumed via `get`, then `item_done` is called
- **THEN** no exception is raised during construction, put, get, or item_done
