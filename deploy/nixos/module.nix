{ config, lib, ... }:

let
  cfg = config.services.mission-control;
  stateDirectory = "/var/lib/mission-control";
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
        Opt in to the synthetic House and Yard showcase data. This is disabled
        by default and is not intended for a production data store.
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
