# Mission Control NixOS module

The flake exports `nixosModules.default` and `nixosModules.mission-control`. The module installs and supervises the same `mctrld` application provided by the portable package.

## Basic configuration

Add Mission Control as a flake input and import its module:

```nix
{
  inputs.mission-control.url = "github:reductist/mission-control";

  outputs = { self, nixpkgs, mission-control, ... }: {
    nixosConfigurations.vectorsigma = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        mission-control.nixosModules.default
        {
          services.mission-control.enable = true;
        }
      ];
    };
  };
}
```

The default service:

- runs as `mission-control.service`
- invokes `mctrld`
- listens on `127.0.0.1:8000`
- stores SQLite data at `/var/lib/mission-control/mission-control.db`
- uses a systemd dynamic user and managed state directory
- restarts after unexpected failures
- does not load demo data

## Deliberate demo mode

Synthetic House and Yard content remains explicitly opt-in:

```nix
services.mission-control = {
  enable = true;
  demo = true;
};
```

Do not point demo mode at a production database.

## Network exposure

The MVP does not yet provide user authentication. The module therefore keeps the loopback default and does not open the firewall.

For Tailscale Serve, leave `host` unchanged and proxy the loopback listener. For direct access on a trusted LAN, set a non-loopback host and add an interface-scoped firewall rule in the host configuration:

```nix
services.mission-control = {
  enable = true;
  host = "0.0.0.0";
};

networking.firewall.interfaces.eno2.allowedTCPPorts = [ 8000 ];
```

A generic global firewall-opening option is intentionally omitted so the application module cannot silently broaden host exposure.

## Available options

```nix
services.mission-control.enable
services.mission-control.package
services.mission-control.databasePath
services.mission-control.host
services.mission-control.port
services.mission-control.demo
```

While the service uses `DynamicUser` and `StateDirectory`, `databasePath` must remain under `/var/lib/mission-control`.
