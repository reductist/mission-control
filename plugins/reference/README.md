# Reference plugin

This directory contains the smallest external-style plugin bundle used to prove
the Mission Control plugin contract.

`configuration.cue` is its configuration authoring source;
`config.schema.json`, `config.defaults.json`, and `config.presentation.json` are
the generated runtime boundary named by `registration.json`. Mission Control
must bind and validate the complete bundle before importing or activating any
plugin implementation.

`runtime.py` is the smallest executable plugin example. It imports only the
public `mission_control.plugin_api` module, receives one scoped activation
context, and returns a `CapabilityRouter`. Its health operation accepts and
returns ordinary JSON-shaped documents. Core validates the versioned call and
result envelopes plus the health document before using it.

The same module also exports the optional storage-free setup entry point. It
returns renderer-neutral setup transitions through `PluginSetupContext` and
never receives a database. Its completed draft is accepted only after core runs
the ordinary generated configuration validator, demonstrating the same setup
authoring path used by the bundled Google Calendar integration.

The reference bundle is exercised by the same validators used for bundled and
third-party plugins. It demonstrates the intended author workflow: describe the
configuration once in CUE, generate portable data artifacts, and keep runtime
code out of configuration validation.

Run its executable conformance check from the repository root:

```console
printf '{"message":"Reference runtime ready"}' > /tmp/reference-settings.json
mcctl plugin conformance plugins/reference/registration.json \
  --settings /tmp/reference-settings.json
```
