## MODIFIED Requirements

### Requirement: NewNode pre-persistence record

The system SHALL provide a `NewNode` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** node record
(one that has not yet been assigned a database `node_id`). Fields:
`ip: str = ""`, `ncpus: int = 0`, `enabled: bool = True`,
`cloud: str | None = None`, `username: str = "root"`, `port: int = 22`.

`NewNode` mirrors the non-`node_id` fields of `Node` with identical defaults,
**except** that `ip` and `ncpus` carry defaults (`""` and `0`) so the
tmp-reservation call site can construct a tmp node without naming them:
`NewNode(cloud=selected_name, enabled=False)`. Field types are unchanged
(`ip: str`, `ncpus: int`) — no `Optional` is introduced. The default `ip=""`
is the empty-string sentinel (see the `Node` "persistent record" requirement
for the invariant); the default `ncpus=0` reflects that a tmp node has no CPU
information until a real VM is provisioned.

`NewNode` carries no identity attribute; it is converted to a `Node` only by
`NodeRepository.insert`. `CloudProvisioner.allocate` returns a `NewNode` (a
freshly-built VM that has not been persisted) with a real `ip` and `ncpus`
populated from the provisioned VM; the caller persists it via `insert` and
receives the `Node`.

#### Scenario: NewNode has no node_id attribute
- **WHEN** a NewNode is instantiated with `ip="10.0.0.1"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None

#### Scenario: NewNode tmp-reservation defaults
- **WHEN** `NewNode(cloud="aws", enabled=False)` is instantiated
- **THEN** `ip` defaults to `""` (empty-string sentinel), `ncpus` defaults to `0`, `username` defaults to `"root"`, `port` defaults to `22`

#### Scenario: CloudProvisioner.allocate returns NewNode with real ip
- **WHEN** `CloudProvisioner.allocate("aws")` is called
- **THEN** it returns a `NewNode` with a real `ip` (the provisioned VM's address) and `ncpus` populated from the VM; the caller passes it to `NodeRepository.insert` to obtain a persisted `Node`