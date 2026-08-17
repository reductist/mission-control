{ self, pkgs }:

pkgs.testers.nixosTest {
  name = "mission-control";

  nodes.machine = { pkgs, ... }: {
    imports = [ self.nixosModules.default ];

    services.mission-control = {
      enable = true;
      demo = true;
      plugins = [ "google-calendar" "landscape" ];
      pluginSettings."google-calendar" = ../../mission_control/builtin_plugins/google/demo-settings.json;
      workspace.principals.patrik = {
        label = "Patrik";
        kind = "person";
      };
    };

    environment.systemPackages = [ pkgs.curl ];
  };

  nodes.credentials = { pkgs, ... }: {
    imports = [ self.nixosModules.default ];

    services.mission-control = {
      enable = true;
      plugins = [ "google-calendar" ];
      pluginSettings."google-calendar" = pkgs.writeText "google-calendar-live-settings" ''
        {
          "connections": {
            "test": {
              "label": "Credential staging test",
              "mode": "live",
              "credential": "oauth",
              "calendars": {"mode": "disabled"},
              "tasks": {"mode": "disabled"}
            }
          },
          "sync_interval_seconds": 86400
        }
      '';
      pluginCredentials."google-calendar".oauth = toString (pkgs.writeText "test-google-oauth" ''
        {"client_id":"test","client_secret":"test","refresh_token":"test"}
      '');
    };
  };

  testScript = ''
    machine.start()
    machine.wait_for_unit("mission-control.service")
    machine.wait_for_open_port(8000)
    machine.succeed(
      "curl --fail --silent http://127.0.0.1:8000/api/health | grep -q '\"status\": \"ok\"'"
    )
    machine.succeed(
      "curl --fail --silent http://127.0.0.1:8000/api/dashboard | grep -q '\"id\": \"measure-access-route\"'"
    )
    machine.succeed(
      "curl --fail --silent http://127.0.0.1:8000/api/dashboard | grep -q '\"entity_type\": \"calendar-event\"'"
    )
    machine.succeed(
      "curl --fail --silent http://127.0.0.1:8000/api/dashboard | grep -q 'Download offline maps'"
    )
    machine.succeed(
      "curl --fail --silent http://127.0.0.1:8000/api/dashboard | grep -q '\"label\": \"Patrik\"'"
    )
    machine.succeed(
      "curl --fail --silent http://127.0.0.1:8000/ | grep -q 'Schedule'"
    )
    machine.succeed(
      "systemctl show mission-control.service --property=DynamicUser --value | grep -qx yes"
    )
    machine.succeed(
      "systemctl show mission-control.service --property=ExecStart --value | grep -q -- '--config'"
    )
    machine.succeed("test -f /var/lib/mission-control/mission-control.db")

    credentials.start()
    credentials.wait_for_unit("mission-control.service")
    credentials.succeed(
      "test $(stat -c %a /run/mission-control/google-calendar-oauth) = 600"
    )
    credentials.succeed(
      "systemctl cat mission-control.service "
      "| grep -Fq 'LoadCredential=google-calendar-oauth:'"
    )
  '';
}
