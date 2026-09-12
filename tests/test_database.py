"""database.py must build the engine from DATABASE_URL, not a hardcoded path."""

from sqlalchemy.pool import StaticPool

import database


def test_engine_uses_the_configured_database_url():
    # conftest sets DATABASE_URL to an in-memory database; if the engine still
    # pointed at the hardcoded sqlite:///./urls.db, the whole suite would be
    # writing to the developer's real database.
    assert ":memory:" in str(database.engine.url)


def test_file_backed_sqlite_disables_the_thread_check():
    options = database.engine_options("sqlite:///./urls.db")

    assert options["connect_args"] == {"check_same_thread": False}
    assert "poolclass" not in options


def test_in_memory_sqlite_pins_a_single_connection():
    # Without StaticPool each connection opens its own empty database.
    assert database.engine_options("sqlite:///:memory:")["poolclass"] is StaticPool


def test_postgres_gets_no_sqlite_arguments():
    # check_same_thread is a SQLite-only DBAPI argument; psycopg2 raises on it.
    assert database.engine_options("postgresql://u:p@localhost:5432/db") == {}


def test_health_endpoint_reports_the_environment(client):
    assert client.get("/health").json() == {"status": "ok", "environment": "development"}
