"""Compatibility imports for the neutral plugin lifecycle.

Bundled implementations remain below this package, while selection, validation,
migrations, and activation are core lifecycle concerns.
"""

from mission_control.plugin_lifecycle import (
    AgendaProvider as BuiltinAgendaProvider,
    PluginLifecycleError as BuiltinPluginError,
    PreparedPlugin as PreparedBuiltinPlugin,
    activate_agenda_plugins as activate_builtin_agenda_plugins,
    bundled_plugin_ids,
    load_agenda_contributions as load_builtin_agenda_contributions,
    prepare_agenda_plugins as prepare_builtin_agenda_plugins,
)

__all__ = [
    "BuiltinAgendaProvider",
    "BuiltinPluginError",
    "PreparedBuiltinPlugin",
    "activate_builtin_agenda_plugins",
    "bundled_plugin_ids",
    "load_builtin_agenda_contributions",
    "prepare_builtin_agenda_plugins",
]
