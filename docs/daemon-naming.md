# Daemon command naming

Mission Control uses `mctrld` for its long-running application server and daemon process.

The earlier `mcd` candidate is not used because it collides with the established Mtools command. `mcctl` remains the administrative command-line interface, while `mission-control.service` remains the systemd unit name.
