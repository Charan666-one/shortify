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
    assert client.get("/health").json() == {
        "status": "ok", "environment": "development", "database": "ok",
    }


def test_every_setting_is_documented_in_env_example():
    """A setting nobody can discover is a setting nobody configures."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = (root / "main.py").read_text() + (root / "database.py").read_text()
    used = set(re.findall(r'os\.getenv\("([A-Z_]+)"', source))
    documented = set(re.findall(
        r"^([A-Z_]+)=", (root / ".env.example").read_text(), re.MULTILINE
    ))

    assert not used - documented, f"undocumented settings: {sorted(used - documented)}"


def test_health_reports_degraded_when_the_database_is_unreachable(client):
    """A health check that only proves the process is alive is worse than none.

    A load balancer keeps routing traffic to an instance whose database has
    gone away, because the process itself still answers.
    """
    from sqlalchemy.exc import OperationalError

    import database
    import main

    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def close(self):
            pass

    main.app.dependency_overrides[database.get_db] = lambda: BrokenSession()
    try:
        response = client.get("/health")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "environment": "development",
        "database": "unreachable",
    }
