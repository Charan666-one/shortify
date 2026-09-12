"""Input validation: URLs in, short codes out."""

import pytest

from main import RESERVED_CODES, app


@pytest.mark.parametrize("url", [
    "",
    "   ",
    "example.com",                 # no scheme
    "javascript:alert(1)",         # not http(s)
    "ftp://example.com/file",
    "http://",                     # no host
])
def test_urls_without_a_valid_http_scheme_and_host_are_rejected(shorten, url):
    assert shorten(url).status_code == 400


@pytest.mark.parametrize("code", [
    "ab",                          # under three characters
    "a" * 51,                      # over fifty
    "a/b",                         # a slash makes the link unroutable
    "<script>x",
    "hello world",
    "café",
    "with.dot",
])
def test_malformed_custom_codes_are_rejected(shorten, code):
    response = shorten("https://example.com", custom=code)

    assert response.status_code == 400, f"{code!r} was accepted"
    assert "Custom code must be" in response.json()["error"]


@pytest.mark.parametrize("code", sorted(RESERVED_CODES))
def test_reserved_codes_are_rejected(shorten, code):
    # Accepting one of these stores a link the router will shadow forever.
    assert shorten("https://example.com", custom=code).status_code == 409


def test_reserved_codes_are_rejected_case_insensitively(shorten):
    assert shorten("https://example.com", custom="Health").status_code == 409


def test_claiming_a_reserved_code_cannot_break_the_real_route(client, shorten):
    shorten("https://evil.example.com", custom="health")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_reserved_set_covers_every_mounted_route():
    """Guard against a new route being added without reserving its path.

    A route like /admin added later would be claimable as a short code until
    its name lands in RESERVED_CODES, and the resulting links would be dead on
    arrival.
    """
    served = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        segments = path.strip("/").split("/")
        first = segments[0]
        if first and "{" not in first:
            served.add(first.lower())

    missing = served - RESERVED_CODES
    assert not missing, f"routes not covered by RESERVED_CODES: {sorted(missing)}"


def test_custom_code_whitespace_is_trimmed(shorten):
    assert shorten("https://example.com", custom="  padded  ").json()["short_code"] == "padded"
