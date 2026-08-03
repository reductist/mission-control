# Packaged schemas

Files in this directory are generated from the canonical CUE definitions under `mission-control/schema/` and packaged with the Python application for runtime validation, including plugin registration, agenda, closed-item, command envelope, and command result contracts.

Do not edit the JSON Schema by hand. `mission-control/scripts/check-schemas.sh` regenerates the contract and fails when the packaged artifact drifts from CUE.
