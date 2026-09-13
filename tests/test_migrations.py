"""The migrations must produce exactly the schema the models describe."""

import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from models import Base

ROOT = Path(__file__).resolve().parent.parent


def _upgrade(db_path):
    """Run `alembic upgrade head` against a throwaway database."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "DATABASE_URL": f"sqlite:///{db_path}"},
        capture_output=True,
        text=True,
    )


def test_migrations_build_the_schema_the_models_expect(tmp_path):
    """Guards the gap that let created_at ship as a lie for months.

    A model column with no migration behind it works locally, where the
    developer's database was built by create_all(), and fails in production
    where it was built by migrations.
    """
    db_path = tmp_path / "migrated.db"
    result = _upgrade(db_path)
    assert result.returncode == 0, result.stderr

    migrated = inspect(create_engine(f"sqlite:///{db_path}"))
    assert "urls" in migrated.get_table_names()

    migrated_columns = {c["name"] for c in migrated.get_columns("urls")}
    model_columns = {c.name for c in Base.metadata.tables["urls"].columns}
    assert migrated_columns == model_columns


def test_migrations_index_the_columns_that_are_looked_up_by(tmp_path):
    db_path = tmp_path / "migrated.db"
    assert _upgrade(db_path).returncode == 0

    indexes = inspect(create_engine(f"sqlite:///{db_path}")).get_indexes("urls")
    by_column = {tuple(i["column_names"]): i for i in indexes}

    # Every redirect looks up short_code; uniqueness is what makes the
    # collision retry correct rather than hopeful.
    # SQLite's inspector reports this as 1 rather than True.
    assert bool(by_column[("short_code",)]["unique"])
    assert ("expires_at",) in by_column
