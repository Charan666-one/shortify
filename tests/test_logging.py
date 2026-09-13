"""Request ids and structured output."""

import io
import json
import logging

import pytest

from logging_config import JsonFormatter, configure_logging, request_id_var


@pytest.fixture
def captured_json():
    """Capture root log output exactly as a production handler would emit it.

    Formatting has to happen at emit time, not afterwards: the request id lives
    in a context variable that is reset once the request ends.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield stream
    finally:
        root.removeHandler(handler)


def test_response_carries_a_request_id(client):
    response = client.get("/health")

    assert len(response.headers["x-request-id"]) == 16


def test_an_upstream_request_id_is_reused(client):
    response = client.get("/health", headers={"X-Request-ID": "upstream-123"})

    # Minting a new id here would break the trail across services.
    assert response.headers["x-request-id"] == "upstream-123"


def test_each_request_gets_its_own_id(client):
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]

    assert first != second


def test_the_request_summary_log_carries_the_id(client, captured_json):
    response = client.get("/health", headers={"X-Request-ID": "trace-me-9"})

    summaries = [
        json.loads(line) for line in captured_json.getvalue().splitlines()
        if line.strip().startswith("{") and json.loads(line).get("path") == "/health"
    ]
    assert summaries, "no request summary was logged"
    assert summaries[-1]["request_id"] == "trace-me-9" == response.headers["x-request-id"]
    assert summaries[-1]["status_code"] == 200
    assert isinstance(summaries[-1]["duration_ms"], float)


def test_extra_fields_become_json_fields(captured_json):
    logging.getLogger("test").info("created", extra={"short_code": "abc123"})

    entry = json.loads(captured_json.getvalue().splitlines()[-1])
    assert entry["short_code"] == "abc123"
    assert entry["message"] == "created"
    assert entry["level"] == "INFO"


def test_the_id_is_cleared_between_requests(client):
    client.get("/health")

    # A leaked id would attach the previous request's trace to background work.
    assert request_id_var.get() == "-"


def test_development_defaults_to_readable_text(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    configure_logging("development")

    handler = logging.getLogger().handlers[0]
    assert not isinstance(handler.formatter, JsonFormatter)


def test_production_defaults_to_json(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    configure_logging("production")

    assert isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)
    configure_logging("development")  # restore for the rest of the session
