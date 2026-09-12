from sqlalchemy import Column, DateTime, Integer, String, func

from database import Base


class URL(Base):
    __tablename__ = "urls"

    id = Column(Integer, primary_key=True, index=True)
    original_url = Column(String, nullable=False)
    short_code = Column(String(50), unique=True, index=True, nullable=False)
    clicks = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # NULL means the link never expires.
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
