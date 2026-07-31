# Mission Control status

_Last updated: 2026-07-31_

## Current phase

**Dogfooding.** Mission Control has a deployed architectural thin slice: a portable Python core, SQLite state and immutable task history, `mcctl`, the `mctrld` browser server, public plugin-registration and agenda contracts, and a declarative NixOS service module. The next phase is to replace synthetic showcase content with one useful household workflow.

## Deployment

| Item | Current state |
| --- | --- |
| Application `main` | `9a4798b551ded0a42076e39a911d4383cc1eec27` |
| Reproducible deployment pin | `e9d6f6a689e2a75a5f499c1ab87971448027dec3` in `reductist/nixconfigs` |
| Runtime revision | Browser demo is operator-confirmed on the trusted LAN; its exact application revision is not yet recorded |
| Service | Current live demo predates convergence on the upstream `services.mission-control` module |

The deployment repository is intentionally behind application `main` while the convergence PR is validated. Until that PR is merged and deployed, the live runtime must not be treated as reproducible from the deployment repository alone.

## Next milestone

Deliver the Landscape/Yard plugin as the first real vertical slice:

- one real property and outdoor site
- the backyard equipment-access initiative
- granular actions, blockers, research notes, and seasonal windows
- at least one observation with an attachment reference
- projection into the shared agenda
- complete, defer, and reopen commands routed to the authoritative plugin owner
- the Overview and Yard views reading the same durable state
- deterministic Markdown export

A wiki plugin is the leading early follow-up because durable notes, decisions, research, and cross-links are central to continued dogfooding.

## Known gaps

- Deployment state has not converged on the current application pin and upstream NixOS module.
- Plugin activation, migrations, lifecycle, query dispatch, and command routing are not implemented end to end.
- House and Yard browser content remains synthetic.
- The MVP has no authentication; direct exposure is suitable only for an explicitly trusted network.
- Backup, restore, upgrade, and recovery procedures are not yet proven with real data.
- The aggregated agenda currently projects core tasks only.
- A full-screen TUI frontend is planned but not implemented.
- The exact live runtime revision and post-restart persistence check are not recorded.

## Last runtime validation

- **2026-07-30:** full host validation for the standalone-repository migration passed, including `nix flake check`, host evaluation and closure build, `nixos-rebuild test`, `mcctl version` (`0.1.0`), firewall health, DNS, binary-cache reachability, and effective SSH policy.
- **2026-07-31:** the browser demo was operator-confirmed listening on `0.0.0.0:8000` with an interface-scoped trusted-LAN firewall opening.
- **Still required after convergence:** record the deployed Mission Control commit; verify `mission-control.service`, `mctrld`, database persistence across restart, the health endpoint from the host and LAN, and the effective interface-scoped firewall rule.
