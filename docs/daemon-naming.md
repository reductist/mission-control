# ADR: Daemon command naming

- **Status:** Accepted
- **Date:** 2026-07-31

## Context

Mission Control needs distinct, stable names for its administrative CLI, long-running application process, systemd unit, and package. The earlier `mcd` candidate collides with the established Mtools command, while `mc` is also widely used.

## Decision

- `mcctl` is the administrative command-line interface.
- `mctrld` is the long-running application server and daemon.
- `mission-control.service` is the systemd unit.
- `mission-control` is the application and distribution package.
- No `mcd` or `mc` compatibility alias is provided.

These names are public interfaces and should not drift casually after the first release.

## Consequences

- Installed commands avoid collisions with established tools.
- Documentation, packaging, deployment adapters, process inspection, and tests use one vocabulary.
- Older experimental references to `mcd` must be corrected rather than preserved as aliases.
