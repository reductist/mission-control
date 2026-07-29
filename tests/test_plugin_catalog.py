from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from mission_control.cli import main
from mission_control.plugins import (
    AvailablePlugin,
    CatalogState,
    ConflictedPlugin,
    PluginCatalog,
    RejectedPlugin,
    build_plugin_catalog,
    discover_registration_sources,
    read_registration_candidate,
    scan_plugin_catalog,
)


REFERENCE_REGISTRATION = (
    Path(__file__).parents[1] / "plugins" / "reference" / "registration.json"
)


def registration_document(plugin_id: str, *, name: str | None = None) -> dict[str, object]:
    document = json.loads(REFERENCE_REGISTRATION.read_text(encoding="utf-8"))
    document["id"] = plugin_id
    document["name"] = name or plugin_id.title()
    return document


def write_registration(root: Path, directory: str, document: object) -> Path:
    plugin_directory = root / directory
    plugin_directory.mkdir(parents=True)
    path = plugin_directory / "registration.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path.resolve()


def test_discovery_is_deterministic_across_multiple_roots(tmp_path):
    first_root = tmp_path / "z-root"
    second_root = tmp_path / "a-root"
    first_root.mkdir()
    second_root.mkdir()

    beta = write_registration(first_root, "beta", registration_document("beta"))
    alpha = write_registration(second_root, "alpha", registration_document("alpha"))

    sources = discover_registration_sources((first_root, second_root))

    assert tuple(source.registration_path for source in sources) == tuple(
        sorted((alpha, beta), key=str)
    )


def test_duplicate_roots_do_not_duplicate_the_same_source(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    registration = write_registration(root, "alpha", registration_document("alpha"))

    sources = discover_registration_sources((root, root, registration))

    assert tuple(source.registration_path for source in sources) == (registration,)


def test_duplicate_plugin_ids_become_one_explicit_conflict(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = write_registration(first_root, "github-a", registration_document("github"))
    second = write_registration(second_root, "github-b", registration_document("github"))

    catalog = scan_plugin_catalog((first_root, second_root))

    assert len(catalog) == 1
    entry = catalog.entries[0]
    assert isinstance(entry, ConflictedPlugin)
    assert entry.state is CatalogState.CONFLICTED
    assert entry.plugin_id.value == "github"
    assert tuple(source.registration_path for source in entry.sources) == tuple(
        sorted((first, second), key=str)
    )


def test_rejected_registration_does_not_abort_valid_catalog_entries(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    valid = write_registration(root, "valid", registration_document("valid"))
    invalid = write_registration(root, "invalid", {"id": "missing-required-fields"})

    catalog = scan_plugin_catalog((root,))

    assert tuple(type(entry) for entry in catalog) == (AvailablePlugin, RejectedPlugin)
    available, rejected = catalog.entries
    assert available.source.registration_path == valid
    assert rejected.source.registration_path == invalid
    assert rejected.state is CatalogState.REJECTED
    assert "required property" in rejected.failure.summary


def test_pure_catalog_builder_accepts_precomputed_candidate_values(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    write_registration(root, "alpha", registration_document("alpha"))
    sources = discover_registration_sources((root,))
    candidates = tuple(read_registration_candidate(source) for source in sources)

    catalog = build_plugin_catalog(candidates)

    assert isinstance(catalog, PluginCatalog)
    assert catalog.entries[0].state is CatalogState.AVAILABLE
    with pytest.raises(FrozenInstanceError):
        catalog.entries = ()  # type: ignore[misc]


def test_cli_lists_catalog_without_initializing_database(tmp_path, capsys):
    root = tmp_path / "plugins"
    root.mkdir()
    source = write_registration(root, "reference", registration_document("reference"))
    database = tmp_path / "must-not-be-created.db"

    assert main(
        [
            "--database",
            str(database),
            "plugin",
            "list",
            "--root",
            str(root),
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == [
        {
            "id": "reference",
            "name": "Reference",
            "source": str(source),
            "state": "available",
            "version": "0.1.0",
        }
    ]
    assert not database.exists()


def test_cli_reports_missing_root_without_initializing_database(tmp_path, capsys):
    database = tmp_path / "must-not-be-created.db"
    missing = tmp_path / "missing"

    assert main(
        [
            "--database",
            str(database),
            "plugin",
            "list",
            "--root",
            str(missing),
        ]
    ) == 2

    captured = capsys.readouterr()
    assert "plugin root does not exist" in captured.err
    assert captured.out == ""
    assert not database.exists()
