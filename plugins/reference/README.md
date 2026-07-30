# Reference plugin

This directory contains the smallest public registration document used to prove the Mission Control plugin contract.

It is intentionally data-only. Mission Control must validate `registration.json` before importing or activating any plugin implementation. Runtime lifecycle hooks, jobs, API handlers, and UI contributions remain outside this slice.

The reference registration is exercised by the same packaged JSON Schema and `mcctl plugin validate` path available to third-party plugins.
