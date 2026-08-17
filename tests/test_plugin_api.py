from __future__ import annotations

from types import SimpleNamespace

import pytest

from mission_control.plugin_api import (
    CapabilityRouter,
    PluginCallContractError,
    PluginCallRejected,
    PluginContext,
    call_plugin,
    validate_plugin_call,
)


def test_capability_router_detaches_and_validates_both_sides() -> None:
    seen = {}

    def health(inputs):
        seen.update(inputs)
        return {"ready": True}

    router = CapabilityRouter("reference", {"health.get": health})

    assert call_plugin(router, "health.get", {}) == {"ready": True}
    assert seen == {}


def test_call_contract_rejects_misspelled_input_before_plugin_code() -> None:
    called = False

    def operation(_inputs):
        nonlocal called
        called = True
        return {}

    router = CapabilityRouter("reference", {"entity-details.get": operation})

    with pytest.raises(PluginCallContractError, match="plugin call violates"):
        router.call(
            {
                "schema_version": "mission-control.plugin-call/v1",
                "operation": "entity-details.get",
                "input": {"source": {}},
            }
        )

    assert called is False


def test_call_result_must_echo_the_requested_operation() -> None:
    handler = SimpleNamespace(
        call=lambda _request: {
            "schema_version": "mission-control.plugin-call-result/v1",
            "operation": "health.get",
            "status": "ok",
            "output": {},
        }
    )

    with pytest.raises(PluginCallContractError, match="does not match"):
        call_plugin(handler, "jobs.list", {})


def test_plugin_rejection_has_a_closed_safe_error_shape() -> None:
    def reject(_inputs):
        raise PluginCallRejected("not-ready", "Try again after setup.")

    router = CapabilityRouter("reference", {"health.get": reject})

    with pytest.raises(PluginCallRejected, match="Try again after setup") as caught:
        call_plugin(router, "health.get", {})

    assert caught.value.code == "not-ready"


def test_plugin_exception_text_is_not_exposed_across_the_call_boundary() -> None:
    handler = SimpleNamespace(
        call=lambda _request: (_ for _ in ()).throw(
            RuntimeError("credential=never-print-this")
        )
    )

    with pytest.raises(PluginCallContractError) as caught:
        call_plugin(handler, "health.get", {})

    assert "RuntimeError" in str(caught.value)
    assert "never-print-this" not in str(caught.value)


def test_plugin_context_is_detached_and_top_level_read_only() -> None:
    source = {"message": "before"}
    context = PluginContext.create(
        plugin_id="reference",
        storage=SimpleNamespace(path="unused"),
        configuration=source,
        credentials={},
    )
    source["message"] = "after"

    assert context.configuration == {"message": "before"}
    with pytest.raises(TypeError):
        context.configuration["message"] = "mutated"  # type: ignore[index]


def test_direct_call_validator_accepts_the_public_fixture_shape() -> None:
    validated = validate_plugin_call(
        {
            "schema_version": "mission-control.plugin-call/v1",
            "operation": "health.get",
            "input": {},
        }
    )

    assert validated["operation"] == "health.get"
