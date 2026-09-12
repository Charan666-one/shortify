"""The create → redirect → stats round trip."""

from datetime import UTC, datetime, timedelta


def test_shorten_returns_201_with_a_usable_code(shorten):
    response = shorten("https://example.com/target")

    assert response.status_code == 201
    body = response.json()
    assert body["original_url"] == "https://example.com/target"
    assert len(body["short_code"]) == 6
    assert body["short_url"].endswith(f"/{body['short_code']}")


def test_short_url_is_built_from_backend_url(shorten):
    # BACKEND_URL is http://testserver in conftest; a link built from anything
    # else (the request host, say) would hand users an unreachable address.
    assert shorten().json()["short_url"].startswith("http://testserver/")


def test_generated_codes_are_url_safe(shorten):
    from main import SHORT_CODE_PATTERN

    codes = {shorten().json()["short_code"] for _ in range(25)}
    assert len(codes) == 25, "generated codes collided"
    assert all(SHORT_CODE_PATTERN.match(code) for code in codes)


def test_custom_code_is_used_verbatim(shorten):
    body = shorten("https://example.com", custom="my-link_1").json()
    assert body["short_code"] == "my-link_1"


def test_duplicate_custom_code_is_rejected(shorten):
    shorten("https://example.com/first", custom="taken")
    response = shorten("https://example.com/second", custom="taken")

    assert response.status_code == 409
    assert "already in use" in response.json()["error"]


def test_redirect_follows_to_the_original_url(client, shorten):
    code = shorten("https://example.com/destination").json()["short_code"]

    response = client.get(f"/{code}", follow_redirects=False)

    assert response.headers["location"] == "https://example.com/destination"


def test_redirect_is_temporary_not_permanent(client, shorten):
    # A 301 is cached by browsers forever: later visits never reach the server,
    # so clicks stop counting and the link can never be retargeted.
    code = shorten().json()["short_code"]

    response = client.get(f"/{code}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"


def test_each_redirect_increments_the_click_count(client, shorten):
    code = shorten().json()["short_code"]

    for _ in range(3):
        client.get(f"/{code}", follow_redirects=False)

    assert client.get(f"/api/stats/{code}").json()["clicks"] == 3


def test_stats_report_a_real_creation_time(client, shorten):
    code = shorten().json()["short_code"]

    created_at = client.get(f"/api/stats/{code}").json()["created_at"]

    # Previously the column did not exist and the endpoint returned "N/A".
    parsed = datetime.fromisoformat(created_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    assert abs(datetime.now(UTC) - parsed) < timedelta(minutes=5)


def test_unknown_code_is_not_found(client):
    assert client.get("/nosuchcode", follow_redirects=False).status_code == 404
    assert client.get("/api/stats/nosuchcode").status_code == 404
