"""Ordered SQLite migration runner."""

from __future__ import annotations

from importlib.resources import files

from .database import Database


class MigrationRunner:
    def __init__(self, database: Database) -> None:
        self.database = database

    def apply(self) -> list[int]:
        applied: list[int] = []
        migration_root = files("mission_control").joinpath("migrations")
        with self.database.connect() as connection:
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            } if self._has_migration_table(connection) else set()

            for migration in sorted(migration_root.iterdir(), key=lambda path: path.name):
                if migration.suffix != ".sql":
                    continue
                version = int(migration.name.split("_", 1)[0])
                if version in existing:
                    continue
                connection.executescript(migration.read_text(encoding="utf-8"))
                applied.append(version)
        return applied

    @staticmethod
    def _has_migration_table(connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        return row is not None
