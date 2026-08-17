"""Renderer-neutral attribution identities and workspace presentation catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from mission_control.plugins import PluginId


class AttributionCatalogError(ValueError):
    """Workspace attribution configuration is internally inconsistent."""


@dataclass(frozen=True, slots=True, order=True)
class PrincipalRef:
    principal_id: str


@dataclass(frozen=True, slots=True, order=True)
class ConnectionRef:
    plugin_id: PluginId
    connection_id: str


@dataclass(frozen=True, slots=True, order=True)
class CollectionRef:
    connection: ConnectionRef
    collection_id: str


@dataclass(frozen=True, slots=True)
class IntegrationAttribution:
    connection: ConnectionRef
    connection_label: str
    collection: CollectionRef | None = None
    collection_kind: str | None = None
    collection_label: str | None = None


@dataclass(frozen=True, slots=True)
class EntryAttribution:
    principals: tuple[PrincipalRef, ...] = ()
    integration: IntegrationAttribution | None = None


@dataclass(frozen=True, slots=True, order=True)
class Principal:
    principal_id: str
    label: str
    kind: str


@dataclass(frozen=True, slots=True)
class AccentPreference:
    token: str
    target: tuple[tuple[str, str], ...]

    @property
    def kind(self) -> str:
        return dict(self.target)["kind"]


@dataclass(frozen=True, slots=True)
class AttributionCatalog:
    principals: tuple[Principal, ...] = ()
    accents: tuple[AccentPreference, ...] = ()

    @classmethod
    def from_workspace(cls, document: object) -> AttributionCatalog:
        if not isinstance(document, Mapping):
            raise AttributionCatalogError("workspace configuration must be an object")
        raw_principals = document.get("principals", {})
        raw_accents = document.get("accents", [])
        if not isinstance(raw_principals, Mapping) or not isinstance(raw_accents, list):
            raise AttributionCatalogError("workspace attribution has an invalid shape")

        principals = tuple(
            Principal(
                str(principal_id),
                str(value["label"]),
                str(value["kind"]),
            )
            for principal_id, value in sorted(raw_principals.items())
            if isinstance(principal_id, str) and isinstance(value, Mapping)
        )
        principal_ids = {principal.principal_id for principal in principals}
        accents: list[AccentPreference] = []
        seen_targets: set[tuple[tuple[str, str], ...]] = set()
        for index, item in enumerate(raw_accents):
            if not isinstance(item, Mapping) or not isinstance(item.get("target"), Mapping):
                raise AttributionCatalogError(
                    f"workspace.accents.{index}: accent must have a typed target"
                )
            target = tuple(
                sorted((str(key), str(value)) for key, value in item["target"].items())
            )
            if target in seen_targets:
                raise AttributionCatalogError(
                    f"workspace.accents.{index}: target is configured more than once"
                )
            seen_targets.add(target)
            target_document = dict(target)
            if (
                target_document.get("kind") == "principal"
                and target_document.get("principal_id") not in principal_ids
            ):
                raise AttributionCatalogError(
                    f"workspace.accents.{index}: principal target is not in the workspace catalog"
                )
            accents.append(AccentPreference(str(item["token"]), target))
        return cls(principals, tuple(accents))

    @property
    def principal_ids(self) -> frozenset[str]:
        return frozenset(principal.principal_id for principal in self.principals)

    def principal(self, principal_id: str) -> Principal | None:
        return next(
            (
                principal
                for principal in self.principals
                if principal.principal_id == principal_id
            ),
            None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mission-control.attribution-catalog/v1",
            "principals": [
                {
                    "id": principal.principal_id,
                    "label": principal.label,
                    "kind": principal.kind,
                }
                for principal in self.principals
            ],
            "accents": [
                {"token": accent.token, "target": dict(accent.target)}
                for accent in self.accents
            ],
        }


def validate_entry_attribution(
    attribution: EntryAttribution, catalog: AttributionCatalog
) -> None:
    unknown = sorted(
        principal.principal_id
        for principal in attribution.principals
        if principal.principal_id not in catalog.principal_ids
    )
    if unknown:
        raise AttributionCatalogError(
            "agenda attribution references unknown workspace principals: "
            + ", ".join(unknown)
        )
