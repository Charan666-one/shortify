"""Concurrency safety around the unique short_code index."""

import main


def test_generated_code_collision_is_retried(client, shorten, monkeypatch):
    """A check-then-insert would 500 here; the retry loop must not.

    generate_short_code is forced to hand out a code that is already taken
    before falling back to a free one, which is exactly what two concurrent
    requests picking the same random code look like to the database.
    """
    shorten("https://example.com/first", custom="dupe01")

    codes = iter(["dupe01", "dupe01", "free01"])
    monkeypatch.setattr(main, "generate_short_code",
                        lambda *args, **kwargs: next(codes))

    response = shorten("https://example.com/second")

    assert response.status_code == 201
    assert response.json()["short_code"] == "free01"


def test_giving_up_after_max_attempts_is_a_500_not_a_crash(client, shorten, monkeypatch):
    shorten("https://example.com/first", custom="always")
    monkeypatch.setattr(main, "generate_short_code",
                        lambda *args, **kwargs: "always")

    response = shorten("https://example.com/second")

    assert response.status_code == 500
    assert "unique short code" in response.json()["error"]


def test_reserved_codes_are_never_generated(client, shorten, monkeypatch):
    codes = iter(["health", "docs", "safe01"])
    monkeypatch.setattr(main, "generate_short_code",
                        lambda *args, **kwargs: next(codes))

    assert shorten().json()["short_code"] == "safe01"
