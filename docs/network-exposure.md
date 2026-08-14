# ADR: Network exposure ownership

- **Status:** Accepted
- **Date:** 2026-07-31

## Context

The MVP browser server does not yet authenticate users. Safe defaults must work for portable installations, while deployment owners still need an explicit way to run a temporary demo on a trusted LAN.

## Decision

The application and upstream deployment adapters default to loopback binding and do not open a firewall. Network exposure belongs to the deployment owner.

A deployment may opt into direct trusted-LAN access by setting a non-loopback bind address and adding an interface-scoped firewall rule. This is an explicit MVP exception for a trusted network, not a portable default or approval for untrusted exposure. Generic global firewall-opening options do not belong in the upstream application module.

Authentication, TLS, reverse-proxy policy, public URLs, and any broader exposure require separate decisions and validation.

Live calendar and task projections can contain private titles, descriptions, locations, and travel plans. A shared household display should therefore use a browser on the same host, an SSH tunnel, or an access-controlled private-network proxy such as Tailscale Serve. Enabling the Google provider does not make the unauthenticated listener safe to expose to a guest LAN or the public internet.

## Consequences

- Installing or enabling Mission Control does not silently broaden network access.
- The application stays independent of interface names, LAN topology, DNS, Tailscale, and ingress choices.
- Deployment reviews must consider the bind address and firewall rule together.
- The direct-LAN demo must be revisited before Mission Control contains sensitive data or reaches an untrusted network.
