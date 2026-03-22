from fastapi import FastAPI
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from database import engine, SessionLocal
from models import URL, Base

import string
import random
from urllib.parse import urlparse

app = FastAPI()

# ✅ Serve frontend (index.html)

app.mount("/static", StaticFiles(directory="static", html=True), name="static")

# ✅ Create DB tables

Base.metadata.create_all(bind=engine)

# ✅ Serve index.html at root

@app.get("/")
def read_root():
    return FileResponse("static/index.html")

# 🔹 Generate random short code

def generate_short_code(length=6):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# 🔹 Ensure unique short code

def generate_unique_code(db):
    while True:
        code = generate_short_code()
        existing = db.query(URL).filter(URL.short_code == code).first()
        if not existing:
            return code

# 🔹 Validate URL

def is_valid_url(url):
    parsed = urlparse(url)
    return bool(parsed.scheme and parsed.netloc)

# 🔹 API: Create short URL

@app.post("/shorten")
def shorten_url(original_url: str, custom: str = None):
    db = SessionLocal()
    try:
        if not is_valid_url(original_url):
            return {"error": "Invalid URL"}

        if custom:
            existing_custom = db.query(URL).filter(URL.short_code == custom).first()
            if existing_custom:
                return {"error": "Custom short code already in use"}
            short_code = custom
        else:
            short_code = generate_unique_code(db)

        new_url = URL(original_url=original_url, short_code=short_code)
        db.add(new_url)
        db.commit()
        db.refresh(new_url)

        return {"short_url": f"http://localhost:8000/{short_code}"}
    finally:
        db.close()

# 🔹 API: Redirect to original URL

@app.get("/{short_code}")
def redirect_url(short_code: str):
    db = SessionLocal()
    try:
        url = db.query(URL).filter(URL.short_code == short_code).first()
        if url:
            url.clicks += 1
            db.commit()
            return RedirectResponse(url.original_url)

        return {"error": "URL not found"}
    finally:
        db.close()
