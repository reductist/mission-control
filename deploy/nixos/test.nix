{ self, pkgs }:

pkgs.testers.nixosTest {
  name = "mission-control";

  nodes.machine = { pkgs, ... }: {
    imports = [ self.nixosModules.default ];

    services.mission-control = {
      enable = true;
      demo = true;
      plugins = [ "google" "landscape" ];
      pluginSettings.google = ../../mission_control/builtin_plugins/google/demo-settings.json;
    };

    environment.systemPackages = [ pkgs.curl ];
  };

  testScript = ''
    start_all()
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
      "curl --fail --silent http://127.0.0.1:8000/ | grep -q 'Schedule'"
    )
    machine.succeed(
      "systemctl show mission-control.service --property=DynamicUser --value | grep -qx yes"
    )
    machine.succeed("test -f /var/lib/mission-control/mission-control.db")
  '';
}
