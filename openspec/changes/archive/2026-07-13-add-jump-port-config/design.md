## Context

`Node.jump_port` and the `yascheduler_nodes.jump_port` column (with `CHECK
0 < jump_port < 65536`, migration 012) have existed since the
node-owns-connection-identity change, but no INI key feeds them. Both stamping
sites — `yasetnode add` (`manage_node._add_node`) and the cloud allocator
(`CloudProvisionerImpl._setup_vm`) — hardcode `jump_port = 22`. The previous
change `node-ncpus-as-config` deliberately deferred `jump_port` from the
`CloudConfig` surface (its delta states "`jump_port` SHALL be `22` ...
`CloudConfig` does not carry a `jump_port` field in this change").

The existing jump-leg resolution rule (established in
node-owns-connection-identity) is atomic: the cloud `CloudConfig` wins the whole
jump leg (host + username) only when it sets BOTH; otherwise the whole leg falls
back to `config.remote.*`. This change extends that rule to port.

No DB schema change is needed — the column and CHECK already exist.

## Goals / Non-Goals

**Goals:**

- Make `jump_port` configurable via `[remote] jump_port` and
  `[clouds.*] {prefix}_jump_port` INI keys.
- Thread the configured value through both stamping sites so an operator whose
  bastion listens on a non-standard port can reach it.
- Preserve the atomic jump-leg rule: a node's `jump_host`, `jump_port`, and
  `jump_username` all come from one source, never mixed.
- Fail fast at `parse_config` on out-of-range ports (mirror the DB CHECK).

**Non-Goals:**

- No DB schema change (column + CHECK already exist from migration 012).
- No change to `MachineRepository.connect` (already reads `node.jump_port`).
- No change to the jump-leg atomicity rule itself (only extends it to port).
- No CLI flag for `jump_port` (`yasetnode` reads it from config, like
  `jump_host`/`jump_username`).
- No `__post_init__` validation on `RemoteDefaults` (parser-side validation
  follows the existing project idiom).

## Decisions

### D1: Atomic jump-leg resolution extended to port

The cloud allocator resolves `jump_port` from the SAME source as
`jump_host` / `jump_username`: `CloudConfig.jump_port` when the cloud leg is
authoritative (both `jump_host` AND `jump_username` set), otherwise
`config.remote.jump_port`.

**Alternative considered: independent port resolution.** Resolve `jump_port`
from `CloudConfig.jump_port` whenever set, regardless of whether host/username
are set. This would allow a mixed leg (cloud port, remote host) — flexible but
surprising and operationally ambiguous (which bastion does the port belong
to?). Rejected: preserves the existing all-or-nothing contract and avoids
mixed-source legs that no operator would intentionally configure.

### D2: Parser-side range validation (1–65535), not `__post_init__`

Validation lives in the per-section parsers (`_parse_remote_section`,
`_parse_*_section`) using the existing `getint` + range-check idiom (already
used for `max_nodes`, `idle_tolerance`, `connect_grace`). Raises `ValueError`
on `< 1`, `> 65535`, or non-integer.

**Alternative considered: `__post_init__` validation on `RemoteDefaults`.**
`RemoteDefaults` currently has NO `__post_init__` (unlike `LocalSettings`).
Adding one introduces a new validation pattern on a DTO the project keeps
validation-free. Rejected: the project's `testing-unit` spec mandates
parser-side validation and the `config-value-objects` spec mandates "no INI
parsing methods" on DTOs; `__post_init__` range checks would split the
validation idiom across two locations.

### D3: `jump_port` on the `CloudConfig` Protocol (not just DTOs)

`CloudConfig` Protocol gains `jump_port: int` as an 8th field (alongside
`jump_host`, `jump_username`). The allocator reads it.

**Alternative considered: keep `jump_port` off the Protocol, hardcode in
allocator.** Rejected: the Protocol documents the application-readable surface;
the allocator reads port alongside host/username, so omitting it from the
Protocol while the DTOs carry it would be inconsistent. The 4 DTOs already
expose `jump_host`/`jump_username` on the Protocol for the same reason.

### D4: Separate change, not folded into `node-ncpus-as-config`

`node-ncpus-as-config` is at 0/37 tasks and its delta explicitly excluded
`jump_port` ("does not carry a `jump_port` field in this change"). Folding
port into it would re-open a spec already written and risk delta conflicts.
A separate small change keeps each proposal's spec coherent.

## Risks / Trade-offs

- **Range mismatch between parser validation and DB CHECK** → mitigated by
  mirroring the exact CHECK bounds (`0 < jump_port < 65536` → valid range
  1–65535). The parser rejects before the row reaches the DB.
- **Backwards compatibility** → default `22` on `RemoteDefaults.jump_port`,
  each `ConfigCloud*.jump_port`, and absent INI keys preserves the exact
  behavior the two stamping sites currently hardcode. Existing INI files behave
  identically.
- **Concurrent-change delta conflict on `cloud/spec.md`** → both this change
  and `node-ncpus-as-config` MODIFY the "CloudProvisionerImpl implements
  CloudProvisioner" requirement. Archiving order matters: whichever archives
  first updates the main spec; the other re-bases against it. Mitigated by
  keeping the MODIFIED block textual-diff-small (only the `jump_port` sentence
  + scenario additions touch port-related lines).
