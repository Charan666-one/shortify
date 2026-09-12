import ipaddress
import logging
import os
import random
import re
import socket
import string
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from database import SessionLocal, engine
from models import URL, Base

# ✅ Load environment variables
load_dotenv()

# ✅ Environment variables with defaults
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./urls.db")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
PORT = int(os.getenv("PORT", 8000))

# Links expire after this many days. 0 disables expiry entirely.
LINK_TTL_DAYS = int(os.getenv("LINK_TTL_DAYS", 365))
MAX_LINK_TTL_DAYS = 3650

# Shorten requests allowed per client per minute. 0 disables the limit.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 20))

# Only trust X-Forwarded-For when a proxy you control sets it. Left on by
# default it would let any client spoof its address and evade the rate limit.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"


# ✅ Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Initialize FastAPI app
app = FastAPI(
    title="URL Shortener (Snip)",
    description="A fast, production-ready URL shortening service",
    version="1.0.0"
)

# ✅ CORS Configuration — origins must include scheme (http://)
dev_origins = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    FRONTEND_URL,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=dev_origins if ENVIRONMENT == "development" else [FRONTEND_URL],
    # No credentials: nothing here authenticates, and credentialed requests
    # combined with a wide origin list are how CORS mistakes become account
    # takeovers once authentication does arrive.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

if ENVIRONMENT == "production" and FRONTEND_URL == "http://localhost:3000":
    logger.warning(
        "ENVIRONMENT=production but FRONTEND_URL is still the localhost "
        "default; browsers on the real frontend will be refused by CORS."
    )

# ✅ Request logging middleware
@app.middleware("http")
async def log_requests(request, call_next):
    logger.info(f"{request.method} {request.url.path}")
    response = await call_next(request)
    return response

# ✅ Serve frontend static files
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

# ✅ Create DB tables
Base.metadata.create_all(bind=engine)

# ✅ Pydantic models
class ShortenRequest(BaseModel):
    original_url: str
    custom: str | None = None
    # None means "use the configured default"; 0 means "never expire".
    expires_in_days: int | None = None

class ShortenResponse(BaseModel):
    short_url: str
    short_code: str
    original_url: str
    expires_at: datetime | None = None

class URLStatsResponse(BaseModel):
    short_code: str
    original_url: str
    clicks: int
    created_at: datetime
    expires_at: datetime | None = None
    expired: bool = False

class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# ✅ Short code rules

# Paths the application serves itself. A short code matching one of these would
# be stored happily and then shadowed forever by the real route, leaving the
# user with a link that can never resolve — so they are refused up front.
# tests/test_validation.py asserts this set still covers every mounted route.
RESERVED_CODES = frozenset({
    "api", "docs", "redoc", "health", "static", "openapi.json",
    "favicon.ico", "robots.txt", "sitemap.xml", ".well-known",
})

# Letters, digits, hyphen and underscore only: anything else is either
# unreachable as a URL path (a slash splits the route) or an injection risk
# downstream. Three characters minimum keeps single letters free for future
# top-level routes.
SHORT_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,50}$")

MAX_CODE_ATTEMPTS = 10


# Hosts that must never be a redirect target. A shortener is a redirect the
# victim's own browser performs, so pointing one at 169.254.169.254 or a
# service on the victim's localhost turns a link into a request they did not
# intend to make, from inside their own network.
BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private        # RFC1918 and friends; covers loopback and link-local
        or ip.is_loopback
        or ip.is_link_local  # includes 169.254.169.254, the cloud metadata address
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def blocked_target_reason(url: str) -> str | None:
    """Return why this URL may not be a redirect target, or None if it may.

    Hostnames are resolved so that a public name pointing at an internal
    address is caught too. Resolution failures are allowed through: a name
    that does not resolve cannot reach anything, and failing closed would take
    the service down with the first DNS hiccup.

    This is a speed bump, not a boundary. DNS can be re-pointed after a link is
    created, so a determined attacker still gets one. It stops the copy-paste
    cases, which is most of them.
    """
    host = urlparse(url).hostname
    if not host:
        return "URL has no host"

    host = host.rstrip(".").lower()
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_HOST_SUFFIXES):
        return f"'{host}' is an internal hostname"

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return f"'{host}' is a private or reserved address" if _is_blocked_ip(literal) else None

    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return None

    for address in resolved:
        try:
            if _is_blocked_ip(ipaddress.ip_address(address)):
                return f"'{host}' resolves to the private or reserved address {address}"
        except ValueError:
            continue
    return None


class FixedWindowRateLimiter:
    """One fixed window per client, counted in this process only.

    Deliberately not a shared store: a single-process limit still blunts the
    script that fills the database, and a Redis-backed limiter is worth adding
    at the same time as the second worker, not before. Behind more than one
    worker the effective limit is this number times the worker count.
    """

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> int:
        """Return 0 if the request is allowed, else seconds until it will be."""
        if self.limit <= 0:
            return 0

        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > 10_000:
                self._prune(now)

            window_start, count = self._hits.get(key, (now, 0))
            if now - window_start >= self.window_seconds:
                window_start, count = now, 0

            if count >= self.limit:
                return max(1, int(self.window_seconds - (now - window_start)))

            self._hits[key] = (window_start, count + 1)
            return 0

    def _prune(self, now: float) -> None:
        expired = [
            key for key, (start, _) in self._hits.items()
            if now - start >= self.window_seconds
        ]
        for key in expired:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


shorten_limiter = FixedWindowRateLimiter(RATE_LIMIT_PER_MINUTE)


def client_key(request: Request) -> str:
    """Identify the caller for rate limiting."""
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the original client; the rest are proxies.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request) -> None:
    retry_after = shorten_limiter.check(client_key(request))
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds",
            headers={"Retry-After": str(retry_after)},
        )


def expiry_for(days: int | None) -> datetime | None:
    """Resolve the expiry timestamp for a new link."""
    ttl = LINK_TTL_DAYS if days is None else days
    if ttl <= 0:
        return None
    return datetime.now(UTC) + timedelta(days=ttl)


# ✅ Helper functions
def generate_short_code(length: int = 6) -> str:
    """Generate a random alphanumeric short code."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def validate_custom_code(custom: str) -> str:
    """Validate a user-supplied short code, returning it stripped."""
    code = custom.strip()
    # Reserved first: names like favicon.ico would otherwise fail the charset
    # rule and report a formatting problem instead of the real reason.
    if code.lower() in RESERVED_CODES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Short code '{code}' is reserved by the application"
        )
    if not SHORT_CODE_PATTERN.match(code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Custom code must be 3–50 characters using only letters, "
                "digits, hyphens and underscores"
            )
        )
    return code

def insert_url(db, original_url: str, short_code: str,
               expires_at: datetime | None = None) -> URL:
    """Insert one URL row, raising IntegrityError if the code is taken."""
    new_url = URL(original_url=original_url, short_code=short_code,
                  expires_at=expires_at)
    db.add(new_url)
    db.commit()
    db.refresh(new_url)
    return new_url

def insert_with_generated_code(db, original_url: str,
                              expires_at: datetime | None = None) -> URL:
    """Insert with a random code, retrying when one is already taken.

    The unique index on short_code is the authority, not a prior SELECT: a
    check-then-insert loses the race between two concurrent requests that pick
    the same code, and the loser gets a 500 instead of a link.
    """
    for _ in range(MAX_CODE_ATTEMPTS):
        code = generate_short_code()
        if code.lower() in RESERVED_CODES:
            continue
        try:
            return insert_url(db, original_url, code, expires_at)
        except IntegrityError:
            db.rollback()
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Could not generate a unique short code after "
               f"{MAX_CODE_ATTEMPTS} attempts"
    )

def is_expired(url: URL) -> bool:
    """True if this link has an expiry that has passed."""
    if url.expires_at is None:
        return False
    expires_at = url.expires_at
    # SQLite hands back naive datetimes; treat those as UTC.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def is_valid_url(url: str) -> bool:
    """Validate URL has http/https scheme and a domain."""
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme in ["http", "https"] and parsed.netloc)
    except Exception:
        return False


# ✅ Endpoints

@app.get("/", tags=["frontend"])
def read_root():
    """Serve the frontend HTML."""
    return FileResponse("static/index.html")


@app.get("/health", tags=["health"])
def health_check():
    """Health check for uptime monitoring."""
    return {"status": "ok", "environment": ENVIRONMENT}


@app.post(
    "/api/shorten",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["shorten"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid URL or custom code"},
        409: {"model": ErrorResponse, "description": "Custom code already in use"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Server error"},
    }
)
def shorten_url(request: Request, payload: ShortenRequest):
    """Create a shortened URL."""
    enforce_rate_limit(request)

    db = SessionLocal()
    try:
        if not payload.original_url.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="original_url cannot be empty"
            )

        if not is_valid_url(payload.original_url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid URL. Must include http:// or https:// scheme"
            )

        blocked = blocked_target_reason(payload.original_url)
        if blocked:
            logger.warning(f"Refused internal target: {payload.original_url} ({blocked})")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot shorten a link to an internal address: {blocked}"
            )

        if payload.expires_in_days is not None and not (
            0 <= payload.expires_in_days <= MAX_LINK_TTL_DAYS
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"expires_in_days must be between 0 and {MAX_LINK_TTL_DAYS}"
            )

        expires_at = expiry_for(payload.expires_in_days)

        if payload.custom:
            custom = validate_custom_code(payload.custom)
            if db.query(URL).filter(URL.short_code == custom).first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Custom short code '{custom}' is already in use"
                )
            try:
                new_url = insert_url(db, payload.original_url, custom, expires_at)
            except IntegrityError:
                # Another request claimed the same code between the check above
                # and this insert; the unique index caught it.
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Custom short code '{custom}' is already in use"
                ) from None
        else:
            new_url = insert_with_generated_code(db, payload.original_url, expires_at)

        logger.info(f"Created: {new_url.short_code} -> {payload.original_url}")

        return ShortenResponse(
            short_url=f"{BACKEND_URL}/{new_url.short_code}",
            short_code=new_url.short_code,
            original_url=payload.original_url,
            expires_at=new_url.expires_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating short URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the short URL"
        ) from e
    finally:
        db.close()


@app.get(
    "/api/stats/{short_code}",
    response_model=URLStatsResponse,
    tags=["stats"],
    responses={
        404: {"model": ErrorResponse, "description": "Short code not found"},
    }
)
def get_url_stats(short_code: str):
    """Get click stats for a shortened URL."""
    db = SessionLocal()
    try:
        url = db.query(URL).filter(URL.short_code == short_code).first()
        if not url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Short code '{short_code}' not found"
            )
        return URLStatsResponse(
            short_code=url.short_code,
            original_url=url.original_url,
            clicks=url.clicks,
            created_at=url.created_at,
            expires_at=url.expires_at,
            expired=is_expired(url),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stats for {short_code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching stats"
        ) from e
    finally:
        db.close()


@app.get(
    "/{short_code}",
    tags=["redirect"],
    responses={
        302: {"description": "Redirect to original URL"},
        404: {"model": ErrorResponse, "description": "Short code not found"},
        410: {"model": ErrorResponse, "description": "Short code has expired"},
        400: {"model": ErrorResponse, "description": "Invalid short code"},
    }
)
def redirect_url(short_code: str):
    """Redirect to original URL and increment click count."""
    if short_code.lower() in RESERVED_CODES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if not short_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Short code cannot be empty"
        )

    db = SessionLocal()
    try:
        url = db.query(URL).filter(URL.short_code == short_code).first()
        if not url:
            logger.warning(f"Not found: {short_code}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Short code '{short_code}' not found"
            )

        if is_expired(url):
            logger.info(f"Expired: {short_code} (expired at {url.expires_at})")
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"Short code '{short_code}' has expired"
            )

        url.clicks += 1
        db.commit()

        logger.info(f"Redirect: {short_code} -> {url.original_url} (clicks: {url.clicks})")
        # 302, not 301: browsers cache a permanent redirect indefinitely, so
        # repeat visits would never reach this handler — click counts would
        # undercount and a link could never be retargeted or taken down.
        return RedirectResponse(
            url=url.original_url,
            status_code=status.HTTP_302_FOUND,
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error redirecting {short_code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during redirect"
        ) from e
    finally:
        db.close()


# ✅ Global HTTP exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    # exc.headers must be forwarded: Retry-After on a 429 is the difference
    # between a client that backs off correctly and one that hammers the door.
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
        headers=getattr(exc, "headers", None),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
