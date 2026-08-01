# ADR: Repository ownership

- **Status:** Accepted
- **Date:** 2026-07-31

## Context

Mission Control began near its first NixOS deployment, but application behavior and host configuration have different release, portability, and security concerns. Keeping application source inside a private host repository would make the first machine an accidental product dependency and obscure which repository owns defects and decisions.

## Decision

`reductist/mission-control` is authoritative for application code, public contracts, built-in and reference plugins, tests, packaging, migrations, releases, product documentation, status, and product issues.

Deployment repositories consume released or exactly pinned Mission Control revisions. They own host assembly, network and firewall policy, storage paths, secrets wiring, service enablement, and host-specific validation. They must use upstream deployment adapters and must not duplicate or privately fork application behavior.

## Consequences

- Product decisions and status remain portable and publicly reviewable.
- A host may select and expose Mission Control without becoming part of the application model.
- Cross-repository changes may require two ordered PRs: application support first, deployment convergence second.
- A live host ahead of its deployment pin is configuration drift and must be called out in `STATUS.md`.
