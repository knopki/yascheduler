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

#### Scenario: UniqueQueue deduplicates under concurrent put on a full queue
- **WHEN** a `UniqueQueue` at `maxsize=1` with a blocking item A has two
  concurrent coroutines attempting `put(Y)` with the same item, both suspended
  inside `super().put()` because the queue is full, and a consumer drains
  the queue via repeated `get()` calls
- **THEN** only one Y is ever enqueued: after the consumer drains `A` and `Y`,
  `q.qsize() == 0`, and exactly one `put` call enqueued the item
