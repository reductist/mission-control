# Reference plugin

This directory contains the smallest external-style plugin bundle used to prove
the Mission Control plugin contract.

It is intentionally data-only. `configuration.cue` is its authoring source;
`config.schema.json`, `config.defaults.json`, and `config.presentation.json` are
the generated runtime boundary named by `registration.json`. Mission Control
must bind and validate the complete bundle before importing or activating any
plugin implementation. Runtime lifecycle hooks, jobs, API handlers, and UI
contributions remain outside this example.

The reference bundle is exercised by the same validators used for bundled and
third-party plugins. It demonstrates the intended author workflow: describe the
configuration once in CUE, generate portable data artifacts, and keep runtime
code out of configuration validation.
