## MODIFIED Requirements

### Requirement: Disconnect and cleanup

The system SHALL support disconnecting specific machines or all machines,
closing SSH connections, cancelling that machine's occupancy monitor (if
any), and removing the machine from the registry.

`disconnect(ip)` SHALL be scoped to the targeted IP. It SHALL cancel only
the background occupancy task registered for `ip` (if present) and SHALL
NOT cancel background tasks registered for any other machine. After
`disconnect(ip)` returns, the occupancy monitors for every other still
connected machine SHALL remain alive and uncanceled.

The system SHALL maintain a one-to-one mapping between a connected machine
IP and its occupancy monitor. Re-registering `start_occupancy_check(ip,
config)` for an already-monitored IP SHALL replace the prior monitor;
the replaced monitor SHALL be cancelled before the new one is installed.

`disconnect_all()` SHALL disconnect every currently connected machine by
invoking `disconnect(ip)` once per machine. The observable aggregate result
(all machines disconnected, all occupancy monitors cancelled) is unchanged.

#### Scenario: Disconnect single machine

- **WHEN** `gateway.disconnect("10.0.0.1")` is called on a connected machine
- **THEN** the SSH connection for `10.0.0.1` is closed, the machine is
  removed from the registry, and any occupancy monitor registered for
  `10.0.0.1` is cancelled and awaited

#### Scenario: Disconnect does not touch other machines' monitors

- **WHEN** machines A, B, and C are connected, each has an occupancy monitor
  registered via `start_occupancy_check`, and `gateway.disconnect("B")` is
  called
- **THEN** only the monitor registered for B is cancelled, the monitors for
  A and C remain alive (not cancelled) and remain registered for their
  respective IPs, and machines A and C stay connected

#### Scenario: Disconnect unknown IP

- **WHEN** `gateway.disconnect("10.0.0.99")` is called for an IP with no
  registered machine
- **THEN** no exception is raised, no occupancy monitor for any other IP is
  cancelled, and the registry of connected machines is unchanged

#### Scenario: Disconnect all

- **WHEN** `gateway.disconnect_all()` is called
- **THEN** every connected machine's SSH connection is closed, every
  connected machine is removed from the registry, and every registered
  occupancy monitor is cancelled

#### Scenario: Re-registering occupancy for an IP replaces the prior monitor

- **WHEN** `start_occupancy_check(ip, config)` is called for an IP that
  already has a live occupancy monitor
- **THEN** the prior monitor is cancelled and the new monitor is installed
  under the same IP key, without affecting monitors registered for other IPs
