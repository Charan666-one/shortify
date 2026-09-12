import logging
import os
import random
import re
import string
from datetime import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
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
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
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

class ShortenResponse(BaseModel):
    short_url: str
    short_code: str
    original_url: str

class URLStatsResponse(BaseModel):
    short_code: str
    original_url: str
    clicks: int
    created_at: datetime

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

def insert_url(db, original_url: str, short_code: str) -> URL:
    """Insert one URL row, raising IntegrityError if the code is taken."""
    new_url = URL(original_url=original_url, short_code=short_code)
    db.add(new_url)
    db.commit()
    db.refresh(new_url)
    return new_url

def insert_with_generated_code(db, original_url: str) -> URL:
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
            return insert_url(db, original_url, code)
        except IntegrityError:
            db.rollback()
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Could not generate a unique short code after "
               f"{MAX_CODE_ATTEMPTS} attempts"
    )

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
        500: {"model": ErrorResponse, "description": "Server error"},
    }
)
def shorten_url(request: ShortenRequest):
    """Create a shortened URL."""
    db = SessionLocal()
    try:
        if not request.original_url.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="original_url cannot be empty"
            )

        if not is_valid_url(request.original_url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid URL. Must include http:// or https:// scheme"
            )

        if request.custom:
            custom = validate_custom_code(request.custom)
            if db.query(URL).filter(URL.short_code == custom).first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Custom short code '{custom}' is already in use"
                )
            try:
                new_url = insert_url(db, request.original_url, custom)
            except IntegrityError:
                # Another request claimed the same code between the check above
                # and this insert; the unique index caught it.
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Custom short code '{custom}' is already in use"
                ) from None
        else:
            new_url = insert_with_generated_code(db, request.original_url)

        logger.info(f"Created: {new_url.short_code} -> {request.original_url}")

        return ShortenResponse(
            short_url=f"{BACKEND_URL}/{new_url.short_code}",
            short_code=new_url.short_code,
            original_url=request.original_url
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
            created_at=url.created_at
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
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
