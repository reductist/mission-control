{
  description = "Portable, plugin-driven self-hosted control plane";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        rec {
          mission-control = pkgs.python3Packages.buildPythonApplication {
            pname = "mission-control";
            version = "0.1.0";
            pyproject = true;
            src = ./.;

            build-system = [
              pkgs.python3Packages.hatchling
            ];

            dependencies = with pkgs.python3Packages; [
              jsonschema
              rich
            ];

            nativeCheckInputs = [
              pkgs.python3Packages.pytestCheckHook
            ];

            pythonImportsCheck = [ "mission_control" ];
          };

          default = mission-control;
        }
      );

      apps = forAllSystems (
        system:
        let
          package = self.packages.${system}.default;
        in
        {
          default = {
            type = "app";
            program = "${package}/bin/mcctl";
          };
          mcctl = {
            type = "app";
            program = "${package}/bin/mcctl";
          };
          mctrld = {
            type = "app";
            program = "${package}/bin/mctrld";
          };
        }
      );

      nixosModules = {
        default = { lib, pkgs, ... }: {
          imports = [ ./deploy/nixos/module.nix ];
          services.mission-control.package = lib.mkDefault (
            self.packages.${pkgs.stdenv.hostPlatform.system}.default
          );
        };

        mission-control = self.nixosModules.default;
      };

      checks = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          package = self.packages.${system}.default;
          nixos-service = import ./deploy/nixos/test.nix {
            inherit self pkgs;
          };
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python3.withPackages (
            packages: with packages; [
              hatchling
              jsonschema
              pytest
              rich
            ]
          );
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.go
            ];
          };
        }
      );
    };
}
