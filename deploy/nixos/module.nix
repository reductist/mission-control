{ config, lib, ... }:

let
  cfg = config.services.mission-control;
  stateDirectory = "/var/lib/mission-control";
  credentialDirectory = "/run/credentials/mission-control.service";
  pluginSettingsArgs = lib.concatMap (
    plugin: [ "--plugin-settings" "${plugin}=${toString cfg.pluginSettings.${plugin}}" ]
  ) (lib.attrNames cfg.pluginSettings);
  pluginCredentialArgs = lib.concatMap (
    plugin:
    lib.concatMap (
      name: [
        "--plugin-credential"
        "${plugin}.${name}=${credentialDirectory}/${plugin}-${name}"
      ]
    ) (lib.attrNames cfg.pluginCredentials.${plugin})
  ) (lib.attrNames cfg.pluginCredentials);
  loadedCredentials = lib.concatMap (
    plugin:
    map (
      name: "${plugin}-${name}:${cfg.pluginCredentials.${plugin}.${name}}"
    ) (lib.attrNames cfg.pluginCredentials.${plugin})
  ) (lib.attrNames cfg.pluginCredentials);
  command = lib.escapeShellArgs (
    [
      "${cfg.package}/bin/mctrld"
      "--database"
      cfg.databasePath
      "--host"
      cfg.host
      "--port"
      (toString cfg.port)
    ]
    ++ lib.optional cfg.demo "--demo"
    ++ lib.concatMap (plugin: [ "--plugin" plugin ]) cfg.plugins
    ++ pluginSettingsArgs
    ++ pluginCredentialArgs
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
        Opt in to the synthetic House showcase data. This is disabled
        by default and is not intended for a production data store.
      '';
    };

    plugins = lib.mkOption {
      type = lib.types.listOf (lib.types.enum [ "google" "landscape" ]);
      default = [ ];
      description = ''
        Bundled read-only agenda providers to load explicitly. General plugin
        lifecycle and third-party activation are not implemented yet.
      '';
    };

    pluginSettings = lib.mkOption {
      type = lib.types.attrsOf lib.types.path;
      default = { };
      description = ''
        Non-secret JSON settings files keyed by enabled plugin ID. Files may
        contain credential names or paths, but never OAuth secret values.
      '';
    };

    pluginCredentials = lib.mkOption {
      type = lib.types.attrsOf (lib.types.attrsOf lib.types.str);
      default = { };
      description = ''
        Runtime credential source paths keyed by plugin ID and credential name.
        Values are passed through systemd LoadCredential and are not copied into
        the Nix store by this module.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
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

      serviceConfig = {
        Type = "simple";
        ExecStart = command;
        Restart = "on-failure";
        RestartSec = "5s";

        DynamicUser = true;
        StateDirectory = "mission-control";
        StateDirectoryMode = "0750";
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
