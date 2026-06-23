import os
import string
import random
import logging
from urllib.parse import urlparse
from typing import Optional

from fastapi import FastAPI, status, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from database import engine, SessionLocal
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
    custom: Optional[str] = None

class ShortenResponse(BaseModel):
    short_url: str
    short_code: str
    original_url: str

class URLStatsResponse(BaseModel):
    short_code: str
    original_url: str
    clicks: int
    created_at: str

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ✅ Helper functions
def generate_short_code(length: int = 6) -> str:
    """Generate a random alphanumeric short code."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_unique_code(db) -> str:
    """Generate a unique short code not already in the database."""
    for _ in range(100):
        code = generate_short_code()
        if not db.query(URL).filter(URL.short_code == code).first():
            return code
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique short code after 100 attempts"
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
            custom = request.custom.strip()
            if len(custom) < 1 or len(custom) > 50:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Custom code must be 1–50 characters"
                )
            if db.query(URL).filter(URL.short_code == custom).first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Custom short code '{custom}' is already in use"
                )
            short_code = custom
        else:
            short_code = generate_unique_code(db)

        new_url = URL(original_url=request.original_url, short_code=short_code)
        db.add(new_url)
        db.commit()
        db.refresh(new_url)

        logger.info(f"Created: {short_code} -> {request.original_url}")

        return ShortenResponse(
            short_url=f"{BACKEND_URL}/{short_code}",
            short_code=short_code,
            original_url=request.original_url
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating short URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the short URL"
        )
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
            created_at=url.created_at.isoformat() if hasattr(url, 'created_at') else "N/A"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stats for {short_code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching stats"
        )
    finally:
        db.close()


@app.get(
    "/{short_code}",
    tags=["redirect"],
    responses={
        301: {"description": "Redirect to original URL"},
        404: {"model": ErrorResponse, "description": "Short code not found"},
        400: {"model": ErrorResponse, "description": "Invalid short code"},
    }
)
def redirect_url(short_code: str):
    """Redirect to original URL and increment click count."""
    if short_code in {"favicon.ico", "robots.txt", "sitemap.xml", ".well-known"}:
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
        return RedirectResponse(url=url.original_url, status_code=status.HTTP_301_MOVED_PERMANENTLY)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error redirecting {short_code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during redirect"
        )
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