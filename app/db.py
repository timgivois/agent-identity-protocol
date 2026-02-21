"""
Database setup and ORM models.
SQLite via SQLAlchemy — zero infra required.
"""
import json
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Float, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone
from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─────────────────────────────────────────────
# Identity (v0.1)
# ─────────────────────────────────────────────

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
    used = Column(String, default="false")


# ─────────────────────────────────────────────
# Orchestration (v0.4)
# ─────────────────────────────────────────────

class RoleRecord(Base):
    """
    A role defines what an agent does.
    Execution happens via a webhook URL — bring your own agent.
    """
    __tablename__ = "roles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    owner_id = Column(String, nullable=False, index=True)
    webhook_url = Column(String, nullable=True)  # POST here to execute
    input_schema = Column(Text, default="{}")    # JSON Schema (stored as text)
    output_schema = Column(Text, default="{}")
    # Heuristic config: e.g. {"min_words": 100, "max_words": 500, "required_keywords": ["brand"]}
    heuristic_config = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WorkflowRecord(Base):
    """
    A workflow is an ordered sequence of nodes.
    Each node references a role and optionally requires a human gate.
    nodes JSON: [{"role_id": "...", "requires_gate": true, "gate_description": "Review copy"}]
    """
    __tablename__ = "workflows"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    owner_id = Column(String, nullable=False, index=True)
    nodes = Column(Text, nullable=False)  # JSON list of node configs
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WorkflowRunRecord(Base):
    """A single execution of a workflow."""
    __tablename__ = "workflow_runs"

    id = Column(String, primary_key=True, index=True)
    workflow_id = Column(String, nullable=False, index=True)
    status = Column(String, default="running")  # running | paused | completed | failed
    current_node_index = Column(Integer, default=0)
    input_data = Column(Text, default="{}")     # Initial input to the workflow
    output_data = Column(Text, nullable=True)   # Final output
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class NodeExecutionRecord(Base):
    """Execution record for a single node within a workflow run."""
    __tablename__ = "node_executions"

    id = Column(String, primary_key=True, index=True)
    workflow_run_id = Column(String, nullable=False, index=True)
    role_id = Column(String, nullable=False)
    node_index = Column(Integer, nullable=False)
    status = Column(String, default="pending")  # pending | running | awaiting_gate | approved | rejected | completed | failed
    input_data = Column(Text, default="{}")
    output_data = Column(Text, nullable=True)
    heuristic_passed = Column(Boolean, nullable=True)
    heuristic_result = Column(Text, nullable=True)  # JSON with details
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class HumanGateRecord(Base):
    """
    A human review gate pausing a node execution.
    Created when a node completes heuristic checks and requires human approval.
    """
    __tablename__ = "human_gates"

    id = Column(String, primary_key=True, index=True)
    node_execution_id = Column(String, nullable=False, index=True)
    workflow_run_id = Column(String, nullable=False, index=True)
    description = Column(Text)
    content_to_review = Column(Text)            # The output to review
    status = Column(String, default="pending")  # pending | claimed | approved | rejected
    reviewer_did = Column(String, nullable=True)
    decision = Column(String, nullable=True)    # approved | rejected
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)


# ─────────────────────────────────────────────
# Marketplace (v1.0)
# ─────────────────────────────────────────────

class ReviewerRecord(Base):
    """
    A human reviewer registered in the marketplace.
    Must have a valid DID from the identity protocol.
    """
    __tablename__ = "reviewers"

    did = Column(String, primary_key=True, index=True)  # FK to agents.did
    display_name = Column(String, nullable=False)
    bio = Column(Text, nullable=True)
    specializations = Column(Text, default="[]")  # JSON list: ["copywriting", "design"]
    reputation_score = Column(Float, default=0.0)
    tasks_completed = Column(Integer, default=0)
    tasks_approved_ratio = Column(Float, default=0.0)  # % of reviews that led to approval
    total_earned = Column(Float, default=0.0)           # Total commission earned (USD)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ReviewTaskRecord(Base):
    """
    A review task created from a human gate.
    Reviewers can claim and complete tasks.
    """
    __tablename__ = "review_tasks"

    id = Column(String, primary_key=True, index=True)
    gate_id = Column(String, nullable=False, index=True)
    reviewer_did = Column(String, nullable=True, index=True)  # set when claimed
    status = Column(String, default="open")  # open | claimed | completed
    commission_usd = Column(Float, default=1.0)  # what reviewer earns on completion
    claimed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    decision = Column(String, nullable=True)   # approved | rejected
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
