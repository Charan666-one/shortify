"""Link expiry: links stop working so a phishing target cannot live forever."""

from datetime import UTC, datetime, timedelta

import main
from database import SessionLocal
from models import URL


def _expire(short_code, when=None):
    """Backdate a link's expiry directly, the way time passing would."""
    db = SessionLocal()
    try:
        url = db.query(URL).filter(URL.short_code == short_code).first()
        url.expires_at = when or datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()


def test_new_links_carry_the_configured_expiry(shorten, monkeypatch):
    monkeypatch.setattr(main, "LINK_TTL_DAYS", 30)

    expires_at = shorten().json()["expires_at"]

    parsed = datetime.fromisoformat(expires_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    expected = datetime.now(UTC) + timedelta(days=30)
    assert abs(expected - parsed) < timedelta(minutes=5)


def test_expiry_can_be_set_per_link(client, monkeypatch):
    monkeypatch.setattr(main, "LINK_TTL_DAYS", 365)

    body = client.post("/api/shorten", json={
        "original_url": "https://example.com/campaign",
        "expires_in_days": 7,
    }).json()

    parsed = datetime.fromisoformat(body["expires_at"])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    # The per-link value wins over the 365-day default.
    assert abs((datetime.now(UTC) + timedelta(days=7)) - parsed) < timedelta(minutes=5)


def test_zero_days_means_never_expires(client):
    response = client.post("/api/shorten", json={
        "original_url": "https://example.com/permanent",
        "expires_in_days": 0,
    })

    assert response.status_code == 201
    assert response.json()["expires_at"] is None


def test_ttl_of_zero_disables_expiry_globally(monkeypatch):
    monkeypatch.setattr(main, "LINK_TTL_DAYS", 0)
    assert main.expiry_for(None) is None


def test_absurd_expiry_is_rejected(client):
    response = client.post("/api/shorten", json={
        "original_url": "https://example.com",
        "expires_in_days": 99999,
    })

    assert response.status_code == 400
    assert "expires_in_days" in response.json()["error"]


def test_negative_expiry_is_rejected(client):
    response = client.post("/api/shorten", json={
        "original_url": "https://example.com",
        "expires_in_days": -5,
    })

    assert response.status_code == 400


def test_an_expired_link_is_gone_not_found(client, shorten):
    code = shorten().json()["short_code"]
    _expire(code)

    response = client.get(f"/{code}", follow_redirects=False)

    # 410 rather than 404: the link existed, which is what a checker needs to
    # know to stop retrying it.
    assert response.status_code == 410
    assert "expired" in response.json()["error"]


def test_an_expired_link_stops_counting_clicks(client, shorten):
    code = shorten().json()["short_code"]
    client.get(f"/{code}", follow_redirects=False)
    _expire(code)
    client.get(f"/{code}", follow_redirects=False)

    assert client.get(f"/api/stats/{code}").json()["clicks"] == 1


def test_stats_report_expiry_state(client, shorten):
    code = shorten().json()["short_code"]
    assert client.get(f"/api/stats/{code}").json()["expired"] is False

    _expire(code)

    body = client.get(f"/api/stats/{code}").json()
    assert body["expired"] is True
    assert body["expires_at"] is not None


def test_a_link_expiring_in_the_future_still_redirects(client, shorten):
    code = shorten().json()["short_code"]
    _expire(code, datetime.now(UTC) + timedelta(days=1))

    assert client.get(f"/{code}", follow_redirects=False).status_code == 302
