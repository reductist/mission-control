{ self, pkgs }:

pkgs.nixosTest {
  name = "mission-control";

  nodes.machine = { pkgs, ... }: {
    imports = [ self.nixosModules.default ];

    services.mission-control = {
      enable = true;
      demo = true;
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
      "systemctl show mission-control.service --property=DynamicUser --value | grep -qx yes"
    )
    machine.succeed("test -f /var/lib/mission-control/mission-control.db")
  '';
}
