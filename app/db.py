"""
Database setup and ORM models.
SQLite via SQLAlchemy — zero infra required.
"""
from sqlalchemy import create_engine, Column, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone
from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}  # SQLite-specific
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class AgentRecord(Base):
    __tablename__ = "agents"

    did = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    owner_id = Column(String, nullable=False, index=True)
    public_key_b64 = Column(String, nullable=False)
    encrypted_private_key = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ChallengeRecord(Base):
    __tablename__ = "challenges"

    nonce = Column(String, primary_key=True, index=True)
    requester_did = Column(String, nullable=False)
    target_did = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    used = Column(String, default="false")  # SQLite has no boolean type natively


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
