"""
Database setup and ORM models.
Supports SQLite (local dev) and PostgreSQL (production) via DATABASE_URL.
"""
import json
from sqlalchemy import (
    create_engine, Column, String, DateTime, Text,
    Integer, Float, Boolean, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone
from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args=settings.db_connect_args,
    pool_pre_ping=True,  # detect stale connections
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _now():
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────
# Auth — API Keys & Users
# ─────────────────────────────────────────────

class UserRecord(Base):
    """Human user (reviewer or workflow owner)."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    email_verified = Column(Boolean, default=False)
    name = Column(String, nullable=True)
    x_handle = Column(String, nullable=True)       # Twitter handle (optional verification)
    role = Column(String, default="reviewer")       # reviewer | owner | admin
    created_at = Column(DateTime, default=_now)
    last_login_at = Column(DateTime, nullable=True)


class ApiKeyRecord(Base):
    """API key for agent authentication."""
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, index=True)
    key_hash = Column(String, unique=True, nullable=False, index=True)  # SHA-256 of raw key
    key_prefix = Column(String, nullable=False)    # first 8 chars (for display)
    agent_did = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=_now)
    last_used_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)


class AgentClaimRecord(Base):
    """Links an agent DID to a human user."""
    __tablename__ = "agent_claims"

    id = Column(String, primary_key=True, index=True)
    agent_did = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=True, index=True)   # set when claimed
    claim_token = Column(String, unique=True, nullable=False, index=True)
    claimed_at = Column(DateTime, nullable=True)
    status = Column(String, default="pending")  # pending | claimed


class MagicLinkRecord(Base):
    """Email magic link for human auth."""
    __tablename__ = "magic_links"

    id = Column(String, primary_key=True, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=False)
    purpose = Column(String, default="login")   # login | verify | claim
    metadata_json = Column(Text, default="{}")  # extra context (e.g. claim_token)
    created_at = Column(DateTime, default=_now)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


# ─────────────────────────────────────────────
# Identity (v0.1)
# ─────────────────────────────────────────────

class AgentRecord(Base):
    __tablename__ = "agents"

    did = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(String, nullable=False, index=True)
    public_key_b64 = Column(String, nullable=False)
    encrypted_private_key = Column(Text, nullable=False)
    is_claimed = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


class ChallengeRecord(Base):
    __tablename__ = "challenges"

    nonce = Column(String, primary_key=True, index=True)
    requester_did = Column(String, nullable=False)
    target_did = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    used = Column(String, default="false")


# ─────────────────────────────────────────────
# Orchestration (v0.4)
# ─────────────────────────────────────────────

class RoleRecord(Base):
    __tablename__ = "roles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    owner_id = Column(String, nullable=False, index=True)
    webhook_url = Column(String, nullable=True)
    input_schema = Column(Text, default="{}")
    output_schema = Column(Text, default="{}")
    heuristic_config = Column(Text, default="{}")
    created_at = Column(DateTime, default=_now)


class WorkflowRecord(Base):
    __tablename__ = "workflows"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    owner_id = Column(String, nullable=False, index=True)
    nodes = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)


class WorkflowRunRecord(Base):
    __tablename__ = "workflow_runs"

    id = Column(String, primary_key=True, index=True)
    workflow_id = Column(String, nullable=False, index=True)
    status = Column(String, default="running")
    current_node_index = Column(Integer, default=0)
    input_data = Column(Text, default="{}")
    output_data = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)
    completed_at = Column(DateTime, nullable=True)


class NodeExecutionRecord(Base):
    __tablename__ = "node_executions"

    id = Column(String, primary_key=True, index=True)
    workflow_run_id = Column(String, nullable=False, index=True)
    role_id = Column(String, nullable=False)
    node_index = Column(Integer, nullable=False)
    status = Column(String, default="pending")
    input_data = Column(Text, default="{}")
    output_data = Column(Text, nullable=True)
    heuristic_passed = Column(Boolean, nullable=True)
    heuristic_result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)
    completed_at = Column(DateTime, nullable=True)


class HumanGateRecord(Base):
    __tablename__ = "human_gates"

    id = Column(String, primary_key=True, index=True)
    node_execution_id = Column(String, nullable=False, index=True)
    workflow_run_id = Column(String, nullable=False, index=True)
    description = Column(Text)
    content_to_review = Column(Text)
    status = Column(String, default="pending")
    reviewer_did = Column(String, nullable=True)
    decision = Column(String, nullable=True)
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)
    resolved_at = Column(DateTime, nullable=True)


# ─────────────────────────────────────────────
# Marketplace (v1.0)
# ─────────────────────────────────────────────

class ReviewerRecord(Base):
    __tablename__ = "reviewers"

    did = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=True, index=True)   # FK to users
    display_name = Column(String, nullable=False)
    bio = Column(Text, nullable=True)
    specializations = Column(Text, default="[]")
    reputation_score = Column(Float, default=0.0)
    tasks_completed = Column(Integer, default=0)
    tasks_approved_ratio = Column(Float, default=0.0)
    total_earned = Column(Float, default=0.0)
    stripe_account_id = Column(String, nullable=True)   # for Stripe Connect payouts
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


class ReviewTaskRecord(Base):
    __tablename__ = "review_tasks"

    id = Column(String, primary_key=True, index=True)
    gate_id = Column(String, nullable=False, index=True)
    reviewer_did = Column(String, nullable=True, index=True)
    status = Column(String, default="open")
    commission_usd = Column(Float, default=1.0)
    claimed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    decision = Column(String, nullable=True)
    feedback = Column(Text, nullable=True)
    stripe_payment_intent_id = Column(String, nullable=True)  # Stripe payment tracking
    created_at = Column(DateTime, default=_now)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
