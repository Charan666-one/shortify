"""Alembic environment.

The connection string is taken from the application's own configuration rather
than alembic.ini, so a migration can never be applied to a different database
than the one the app is about to serve.
"""

from logging.config import fileConfig

from alembic import context

from database import DATABASE_URL, engine_options
from models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rewrites the
        # table instead, so the same migration runs on SQLite and Postgres.
        render_as_batch=DATABASE_URL.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    from sqlalchemy import create_engine

    connectable = create_engine(DATABASE_URL, **engine_options(DATABASE_URL))

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=DATABASE_URL.startswith("sqlite"),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
