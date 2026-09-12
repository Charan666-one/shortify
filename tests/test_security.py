"""Redirect-target blocking, rate limiting and CORS."""

import pytest

import main


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/admin",
    "http://localhost:9000/",
    "http://10.0.0.5/internal",
    "http://192.168.1.1/router",
    "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://[::1]:8000/",
    "http://0.0.0.0/",
    "http://jenkins.internal/job/deploy",
    "http://printer.local/",
    "http://metadata.google.internal/",
])
def test_internal_targets_are_refused(shorten, url):
    """A short link is a redirect the victim's own browser performs."""
    response = shorten(url)

    assert response.status_code == 400, f"{url} was accepted"
    assert "internal address" in response.json()["error"]


def test_trailing_dot_does_not_bypass_the_block(shorten):
    # "localhost." is the same host to a resolver.
    assert shorten("http://localhost./admin").status_code == 400


def test_uppercase_host_does_not_bypass_the_block(shorten):
    assert shorten("http://LOCALHOST/admin").status_code == 400


def test_public_targets_are_still_accepted(shorten):
    assert shorten("https://example.com/article").status_code == 201


def test_unresolvable_hosts_are_allowed_through(shorten):
    # Failing closed would take the whole service down with one DNS hiccup,
    # and a name that does not resolve cannot reach anything anyway.
    assert shorten("https://nonexistent-host-for-tests.invalid/x").status_code == 201


def test_public_ip_literals_are_allowed(shorten):
    # 172.66.x is outside RFC1918's 172.16/12 — a real Cloudflare address.
    assert shorten("https://172.66.147.243/").status_code == 201


class TestRateLimit:
    def test_requests_over_the_limit_are_refused(self, shorten, monkeypatch):
        monkeypatch.setattr(main.shorten_limiter, "limit", 3)
        main.shorten_limiter.reset()

        for _ in range(3):
            assert shorten().status_code == 201

        response = shorten()
        assert response.status_code == 429
        assert response.headers["retry-after"].isdigit()
        assert "Rate limit exceeded" in response.json()["error"]

    def test_a_limit_of_zero_disables_the_check(self, shorten, monkeypatch):
        monkeypatch.setattr(main.shorten_limiter, "limit", 0)
        main.shorten_limiter.reset()

        for _ in range(30):
            assert shorten().status_code == 201

    def test_the_window_rolls_over(self, monkeypatch):
        limiter = main.FixedWindowRateLimiter(limit=2, window_seconds=60)

        assert limiter.check("client", now=1000.0) == 0
        assert limiter.check("client", now=1001.0) == 0
        assert limiter.check("client", now=1002.0) > 0, "third request should be refused"
        assert limiter.check("client", now=1062.0) == 0, "new window should allow it"

    def test_clients_are_counted_separately(self):
        limiter = main.FixedWindowRateLimiter(limit=1, window_seconds=60)

        assert limiter.check("a", now=0.0) == 0
        assert limiter.check("b", now=0.0) == 0
        assert limiter.check("a", now=0.0) > 0

    def test_retry_after_counts_down_within_the_window(self):
        limiter = main.FixedWindowRateLimiter(limit=1, window_seconds=60)
        limiter.check("client", now=0.0)

        assert limiter.check("client", now=30.0) == 30
        assert limiter.check("client", now=59.5) == 1  # never returns 0 while blocked


class TestProxyHeaders:
    def _request(self, headers):
        class FakeClient:
            host = "10.1.2.3"

        class FakeRequest:
            client = FakeClient()

        request = FakeRequest()
        request.headers = headers
        return request

    def test_forwarded_header_is_ignored_by_default(self, monkeypatch):
        monkeypatch.setattr(main, "TRUST_PROXY_HEADERS", False)

        key = main.client_key(self._request({"x-forwarded-for": "1.2.3.4"}))

        # Trusting it by default would let any client spoof a fresh identity
        # per request and walk straight past the limit.
        assert key == "10.1.2.3"

    def test_forwarded_header_is_used_when_trusted(self, monkeypatch):
        monkeypatch.setattr(main, "TRUST_PROXY_HEADERS", True)

        key = main.client_key(self._request({"x-forwarded-for": "1.2.3.4, 10.0.0.1"}))

        assert key == "1.2.3.4"


def test_cors_does_not_allow_credentials(client):
    response = client.options(
        "/api/shorten",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-credentials" not in response.headers
