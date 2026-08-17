# Mission Control NixOS module

The flake exports `nixosModules.default` and `nixosModules.mission-control`. The module installs and supervises the same `mctrld` application provided by the portable package.

The module's Nix options are an adapter: they generate
`mission-control.config/v1` TOML and start `mctrld --config` with that document.
They do not implement alternate plugin, default, credential, or validation
semantics.

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
- does not load demo data or bundled providers

## Deliberate demo mode

Synthetic House content remains explicitly opt-in. The real read-only Yard
slice is selected separately through the bundled Landscape provider:

```nix
services.mission-control = {
  enable = true;
  demo = true;
  plugins = [ "google-calendar" "landscape" ];
  pluginSettings."google-calendar" = ./google-demo-settings.json;
};
```

`demo = true` enables the House showcase only. Google fixture mode remains an
explicit, plugin-owned setting so the core never changes a provider's source.
The referenced settings file contains `{ "mode": "demo" }`.

Google fixture mode requires no credential. For live mode, keep non-secret settings in a JSON path and provide the authorized-user credential through systemd's credential mechanism:

```nix
services.mission-control = {
  enable = true;
  plugins = [ "google-calendar" ];
  pluginSettings."google-calendar" = ./google-settings.json;
  pluginCredentials."google-calendar".oauth = "/run/secrets/mission-control-google-oauth.json";
};
```

Additional installable providers can be discovered with `pluginRoots`. Their
manifest resources may live outside the bundled package, but the Python module
declared by each runtime entrypoint must already be installed in the service's
package closure.

The settings file may enter the Nix store and must not contain OAuth values. The module decodes it into the plugin's namespaced settings in the generated canonical TOML. The credential source is loaded by PID 1 into the service's private `/run/credentials` directory; only that runtime file reference appears in configuration, and secret contents are not copied into the store or passed as process arguments. See [`../../docs/google-integration.md`](../../docs/google-integration.md) for the settings and OAuth contract.

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
services.mission-control.plugins
services.mission-control.pluginRoots
services.mission-control.pluginSettings
services.mission-control.pluginCredentials
```

While the service uses `DynamicUser` and `StateDirectory`, `databasePath` must remain under `/var/lib/mission-control`.
