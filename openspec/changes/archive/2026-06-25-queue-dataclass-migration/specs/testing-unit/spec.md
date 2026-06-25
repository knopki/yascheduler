## MODIFIED Requirements

### Requirement: UniqueQueue

Tests SHALL verify `UniqueQueue` and `UMessage`: put/get, deduplication,
`item_done` tracking, re-queueing after done, `psize` reflects in-flight,
`task_done` raises `NotImplementedError`.

Deduplication in `UniqueQueue` SHALL be keyed on the message `id`. Two
`UMessage` instances with equal `id` SHALL be treated as duplicates regardless
of their `payload`. The `payload` field SHALL NOT participate in `__eq__` or
`__hash__`; therefore an unhashable `payload` (e.g. a `dict`) SHALL be
accepted at construction and during enqueue/get/item_done operations.

#### Scenario: UniqueQueue deduplicates identical items
- **WHEN** the same item (equal `id`) is put twice before being consumed
- **THEN** the second put is ignored and queue size does not increase
