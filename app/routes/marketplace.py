"""
Reviewer marketplace (v1.0).

Reviewers are humans with verified DIDs who review agent output at human gates.
They earn commission per completed task and build on-chain reputation.

Flow:
  1. Human registers as reviewer (must have a DID from the identity protocol)
  2. Open tasks appear in the marketplace (one per pending gate)
  3. Reviewer claims a task (locks it to them)
  4. Reviewer submits decision (approved/rejected + feedback)
  5. Commission is tracked; reputation score is updated
  6. Over time: gates with consistent approval patterns can be automated
"""
import json
import uuid
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..db import (
    get_db, ReviewerRecord, ReviewTaskRecord, HumanGateRecord,
    AgentRecord
)
from ..core.executor import resume_after_gate

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ─── Schemas ───────────────────────────────────────

class ReviewerRegisterRequest(BaseModel):
    did: str
    display_name: str
    bio: Optional[str] = None
    specializations: Optional[list[str]] = []


class ReviewerResponse(BaseModel):
    did: str
    display_name: str
    bio: Optional[str]
    specializations: list[str]
    reputation_score: float
    tasks_completed: int
    tasks_approved_ratio: float
    total_earned: float
    is_active: bool
    created_at: datetime

    @classmethod
    def from_record(cls, r: ReviewerRecord) -> "ReviewerResponse":
        return cls(
            did=r.did,
            display_name=r.display_name,
            bio=r.bio,
            specializations=json.loads(r.specializations or "[]"),
            reputation_score=r.reputation_score,
            tasks_completed=r.tasks_completed,
            tasks_approved_ratio=r.tasks_approved_ratio,
            total_earned=r.total_earned,
            is_active=r.is_active,
            created_at=r.created_at,
        )


class ReviewTaskResponse(BaseModel):
    id: str
    gate_id: str
    reviewer_did: Optional[str]
    status: str
    commission_usd: float
    content_to_review: Optional[str]
    gate_description: Optional[str]
    decision: Optional[str]
    feedback: Optional[str]
    claimed_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    @classmethod
    def from_records(cls, task: ReviewTaskRecord, gate: HumanGateRecord) -> "ReviewTaskResponse":
        return cls(
            id=task.id,
            gate_id=task.gate_id,
            reviewer_did=task.reviewer_did,
            status=task.status,
            commission_usd=task.commission_usd,
            content_to_review=gate.content_to_review if gate else None,
            gate_description=gate.description if gate else None,
            decision=task.decision,
            feedback=task.feedback,
            claimed_at=task.claimed_at,
            completed_at=task.completed_at,
            created_at=task.created_at,
        )


class ClaimTaskRequest(BaseModel):
    reviewer_did: str


class CompleteTaskRequest(BaseModel):
    reviewer_did: str
    decision: str   # "approved" | "rejected"
    feedback: Optional[str] = None


class LeaderboardEntry(BaseModel):
    rank: int
    did: str
    display_name: str
    reputation_score: float
    tasks_completed: int
    total_earned: float


# ─── Reviewer endpoints ────────────────────────────

@router.post("/reviewers", response_model=ReviewerResponse, status_code=201)
def register_reviewer(req: ReviewerRegisterRequest, db: Session = Depends(get_db)):
    """
    Register as a reviewer. Must have a valid DID from the identity protocol.
    Your DID is your verifiable identity — no username/password.
    """
    # Verify DID exists in the identity system
    agent = db.query(AgentRecord).filter(AgentRecord.did == req.did).first()
    if not agent:
        raise HTTPException(
            status_code=400,
            detail=f"DID not found in identity registry. Register your agent DID first: POST /agents/register"
        )

    existing = db.query(ReviewerRecord).filter(ReviewerRecord.did == req.did).first()
    if existing:
        raise HTTPException(status_code=409, detail="Reviewer already registered with this DID")

    reviewer = ReviewerRecord(
        did=req.did,
        display_name=req.display_name,
        bio=req.bio,
        specializations=json.dumps(req.specializations or []),
    )
    db.add(reviewer)
    db.commit()
    db.refresh(reviewer)
    return ReviewerResponse.from_record(reviewer)


@router.get("/reviewers", response_model=list[ReviewerResponse])
def list_reviewers(db: Session = Depends(get_db)):
    reviewers = db.query(ReviewerRecord).filter(ReviewerRecord.is_active == True).all()
    return [ReviewerResponse.from_record(r) for r in reviewers]


@router.get("/reviewers/{did:path}", response_model=ReviewerResponse)
def get_reviewer(did: str, db: Session = Depends(get_db)):
    reviewer = db.query(ReviewerRecord).filter(ReviewerRecord.did == did).first()
    if not reviewer:
        raise HTTPException(status_code=404, detail="Reviewer not found")
    return ReviewerResponse.from_record(reviewer)


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def get_leaderboard(limit: int = 10, db: Session = Depends(get_db)):
    """Top reviewers by reputation score."""
    reviewers = (
        db.query(ReviewerRecord)
        .filter(ReviewerRecord.is_active == True)
        .order_by(ReviewerRecord.reputation_score.desc())
        .limit(limit)
        .all()
    )
    return [
        LeaderboardEntry(
            rank=i + 1,
            did=r.did,
            display_name=r.display_name,
            reputation_score=r.reputation_score,
            tasks_completed=r.tasks_completed,
            total_earned=r.total_earned,
        )
        for i, r in enumerate(reviewers)
    ]


# ─── Task endpoints ────────────────────────────────

@router.get("/tasks", response_model=list[ReviewTaskResponse])
def list_tasks(status: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Browse available review tasks.
    Filter by status: open | claimed | completed
    """
    q = db.query(ReviewTaskRecord)
    if status:
        q = q.filter(ReviewTaskRecord.status == status)
    tasks = q.order_by(ReviewTaskRecord.created_at.desc()).all()

    results = []
    for task in tasks:
        gate = db.query(HumanGateRecord).filter(HumanGateRecord.id == task.gate_id).first()
        results.append(ReviewTaskResponse.from_records(task, gate))
    return results


@router.get("/tasks/{task_id}", response_model=ReviewTaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(ReviewTaskRecord).filter(ReviewTaskRecord.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    gate = db.query(HumanGateRecord).filter(HumanGateRecord.id == task.gate_id).first()
    return ReviewTaskResponse.from_records(task, gate)


@router.post("/tasks/{task_id}/claim", response_model=ReviewTaskResponse)
def claim_task(task_id: str, req: ClaimTaskRequest, db: Session = Depends(get_db)):
    """
    Claim a review task. Locks it to you — others can't claim it.
    You have the task's content to review and can then submit your decision.
    """
    task = db.query(ReviewTaskRecord).filter(ReviewTaskRecord.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "open":
        raise HTTPException(status_code=400, detail=f"Task is already {task.status}")

    reviewer = db.query(ReviewerRecord).filter(ReviewerRecord.did == req.reviewer_did).first()
    if not reviewer:
        raise HTTPException(status_code=400, detail="Reviewer not registered. POST /marketplace/reviewers first.")

    task.reviewer_did = req.reviewer_did
    task.status = "claimed"
    task.claimed_at = datetime.now(timezone.utc)

    gate = db.query(HumanGateRecord).filter(HumanGateRecord.id == task.gate_id).first()
    if gate:
        gate.reviewer_did = req.reviewer_did
        gate.status = "claimed"

    db.commit()
    db.refresh(task)
    return ReviewTaskResponse.from_records(task, gate)


@router.post("/tasks/{task_id}/complete", response_model=ReviewTaskResponse)
def complete_task(task_id: str, req: CompleteTaskRequest, db: Session = Depends(get_db)):
    """
    Submit your review decision and earn commission.

    - approved → workflow continues to next node
    - rejected → workflow stops (requester must retry)

    Reputation score is updated based on decision consistency over time.
    """
    task = db.query(ReviewTaskRecord).filter(ReviewTaskRecord.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "completed":
        raise HTTPException(status_code=400, detail="Task already completed")

    if task.reviewer_did != req.reviewer_did:
        raise HTTPException(status_code=403, detail="This task is claimed by a different reviewer")

    if req.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")

    # Complete the task
    task.decision = req.decision
    task.feedback = req.feedback
    task.status = "completed"
    task.completed_at = datetime.now(timezone.utc)
    db.commit()

    # Resolve the gate and resume workflow
    gate = db.query(HumanGateRecord).filter(HumanGateRecord.id == task.gate_id).first()
    if gate:
        gate.decision = req.decision
        gate.feedback = req.feedback
        gate.reviewer_did = req.reviewer_did
        gate.status = req.decision
        gate.resolved_at = datetime.now(timezone.utc)
        db.commit()
        resume_after_gate(gate, db)

    # Update reviewer stats + reputation
    reviewer = db.query(ReviewerRecord).filter(ReviewerRecord.did == req.reviewer_did).first()
    if reviewer:
        reviewer.tasks_completed += 1
        reviewer.total_earned += task.commission_usd

        # Recalculate approval ratio
        all_tasks = db.query(ReviewTaskRecord).filter(
            ReviewTaskRecord.reviewer_did == req.reviewer_did,
            ReviewTaskRecord.status == "completed"
        ).all()
        approved_count = sum(1 for t in all_tasks if t.decision == "approved")
        reviewer.tasks_approved_ratio = approved_count / len(all_tasks) if all_tasks else 0.0

        # Reputation score: weighted by tasks completed + approval ratio
        # Simple formula: log scale of completions * approval ratio quality factor
        import math
        completions_factor = math.log(reviewer.tasks_completed + 1, 10) * 10
        quality_factor = reviewer.tasks_approved_ratio
        consistency_bonus = 5.0 if reviewer.tasks_completed >= 10 else 0.0
        reviewer.reputation_score = round(
            (completions_factor * 0.5 + quality_factor * 50 + consistency_bonus), 2
        )
        db.commit()

    db.refresh(task)
    return ReviewTaskResponse.from_records(task, gate)


@router.get("/stats", tags=["marketplace"])
def get_marketplace_stats(db: Session = Depends(get_db)):
    """Marketplace overview stats."""
    total_reviewers = db.query(ReviewerRecord).count()
    open_tasks = db.query(ReviewTaskRecord).filter(ReviewTaskRecord.status == "open").count()
    claimed_tasks = db.query(ReviewTaskRecord).filter(ReviewTaskRecord.status == "claimed").count()
    completed_tasks = db.query(ReviewTaskRecord).filter(ReviewTaskRecord.status == "completed").count()
    total_commission = db.query(ReviewerRecord).with_entities(
        ReviewerRecord.total_earned
    ).all()
    total_paid = sum(r.total_earned for r in db.query(ReviewerRecord).all())

    return {
        "reviewers": total_reviewers,
        "tasks": {
            "open": open_tasks,
            "claimed": claimed_tasks,
            "completed": completed_tasks,
            "total": open_tasks + claimed_tasks + completed_tasks,
        },
        "total_commission_paid_usd": round(total_paid, 2),
    }
