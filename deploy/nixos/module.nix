{ config, lib, pkgs, ... }:

let
  cfg = config.services.mission-control;
  stateDirectory = "/var/lib/mission-control";
  credentialDirectory = "/run/credentials/mission-control.service";
  runtimeDirectory = "/run/mission-control";
  toml = pkgs.formats.toml { };
  pluginConfiguration = lib.genAttrs cfg.plugins (
    plugin:
    {
      enabled = true;
    }
    // lib.optionalAttrs (lib.hasAttr plugin cfg.pluginSettings) {
      settings = builtins.fromJSON (
        builtins.readFile cfg.pluginSettings.${plugin}
      );
    }
    // lib.optionalAttrs (lib.hasAttr plugin cfg.pluginCredentials) {
      credentials = lib.mapAttrs (
        name: _source: {
          file = "${runtimeDirectory}/${plugin}-${name}";
        }
      ) cfg.pluginCredentials.${plugin};
    }
  );
  applicationConfig = toml.generate "mission-control.toml" {
    schema_version = "mission-control.config/v1";
    database.path = cfg.databasePath;
    http = {
      host = cfg.host;
      port = cfg.port;
    };
    demo = cfg.demo;
    plugin_roots = map toString cfg.pluginRoots;
     plugins = pluginConfiguration;
   };
  loadedCredentials = lib.concatMap (
    plugin:
    map (
      name: "${plugin}-${name}:${cfg.pluginCredentials.${plugin}.${name}}"
    ) (lib.attrNames cfg.pluginCredentials.${plugin})
  ) (lib.attrNames cfg.pluginCredentials);
  copyCredentials = lib.concatStringsSep "\n" (lib.concatMap (
    plugin:
      map (
        name: ''
          ${pkgs.coreutils}/bin/install -m 0600 \
            ${lib.escapeShellArg "${credentialDirectory}/${plugin}-${name}"} \
            ${lib.escapeShellArg "${runtimeDirectory}/${plugin}-${name}"}
        ''
      ) (lib.attrNames cfg.pluginCredentials.${plugin})
  ) (lib.attrNames cfg.pluginCredentials));
  command = lib.escapeShellArgs (
    [
      "${cfg.package}/bin/mctrld"
      "--config"
      applicationConfig
    ]
  );
in
{
  options.services.mission-control = {
    enable = lib.mkEnableOption "Mission Control";

    package = lib.mkOption {
      type = lib.types.package;
      description = "Mission Control package containing mcctl and mctrld.";
    };

    databasePath = lib.mkOption {
      type = lib.types.str;
      default = "${stateDirectory}/mission-control.db";
      description = ''
        SQLite database path. The initial service module uses a dynamic systemd
        user and only grants write access to ${stateDirectory}.
      '';
    };

    host = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = ''
        Address on which mctrld listens. Keep the loopback default unless the
        deployment has an explicit trusted-network or reverse-proxy boundary.
      '';
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8000;
      description = "TCP port on which mctrld listens.";
    };

    demo = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Opt in to the synthetic House showcase data. Provider fixture modes
        are configured independently through pluginSettings. This is disabled
        by default and is not intended for a production data store.
      '';
    };

    plugins = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = ''
        Bundled agenda providers to load explicitly by their manifest ID.
      '';
    };

    pluginRoots = lib.mkOption {
      type = lib.types.listOf lib.types.path;
      default = [ ];
      description = ''
        Additional manifest/resource roots to discover. Python runtime modules
        named by those manifests must already be present in the package closure.
      '';
    };

    pluginSettings = lib.mkOption {
      type = lib.types.attrsOf lib.types.path;
      default = { };
      description = ''
        Non-secret JSON settings files keyed by enabled plugin ID. Files may
        not contain credential paths or secret values; use pluginCredentials
        for every credential reference.
      '';
    };

    pluginCredentials = lib.mkOption {
      type = lib.types.attrsOf (lib.types.attrsOf lib.types.str);
      default = { };
      description = ''
        Runtime credential source paths keyed by plugin ID and credential name.
        Values are passed through systemd LoadCredential, copied into the
        service's private ephemeral runtime directory with mode 0600, and are
        not copied into the Nix store by this module.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = lib.length cfg.plugins == lib.length (lib.unique cfg.plugins);
        message = "services.mission-control.plugins must not contain duplicates";
      }
      {
        assertion =
          cfg.databasePath == stateDirectory
          || lib.hasPrefix "${stateDirectory}/" cfg.databasePath;
        message = ''
          services.mission-control.databasePath must remain within
          ${stateDirectory} while the service uses DynamicUser and StateDirectory.
        '';
      }
      {
        assertion = lib.all (plugin: lib.elem plugin cfg.plugins) (
          lib.attrNames cfg.pluginSettings
        );
        message = "services.mission-control.pluginSettings may only configure enabled plugins";
      }
      {
        assertion = lib.all (plugin: lib.elem plugin cfg.plugins) (
          lib.attrNames cfg.pluginCredentials
        );
        message = "services.mission-control.pluginCredentials may only configure enabled plugins";
      }
    ];

    systemd.services.mission-control = {
      description = "Mission Control";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];

      environment.PYTHONUNBUFFERED = "1";
      preStart = copyCredentials;

      serviceConfig = {
        Type = "simple";
        ExecStart = command;
        Restart = "on-failure";
        RestartSec = "5s";

        DynamicUser = true;
        StateDirectory = "mission-control";
        StateDirectoryMode = "0750";
        RuntimeDirectory = "mission-control";
        RuntimeDirectoryMode = "0700";
        WorkingDirectory = stateDirectory;
        UMask = "0077";
        LoadCredential = loadedCredentials;

        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateTmp = true;
        ProtectControlGroups = true;
        ProtectHome = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        CapabilityBoundingSet = "";
        AmbientCapabilities = "";
      };
    };
  };
}
