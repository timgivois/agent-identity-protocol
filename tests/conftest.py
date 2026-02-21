"""
Shared test fixtures — single DB, proper isolation.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, get_db

# One in-memory DB for the whole test suite
TEST_DB_URL = "sqlite:///./test_shared.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


# Apply override once at collection time
app.dependency_overrides[get_db] = override_db


@pytest.fixture(autouse=True)
def reset_db():
    """Drop and recreate all tables before each test — full isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
