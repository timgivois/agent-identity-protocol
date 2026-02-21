"""
Human gate management.

Gates pause workflow execution pending human review.
After a reviewer approves or rejects, the workflow resumes (or fails).
"""
import json
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..db import get_db, HumanGateRecord, NodeExecutionRecord, ReviewTaskRecord
from ..core.executor import resume_after_gate

router = APIRouter(prefix="/gates", tags=["orchestration"])


class GateResponse(BaseModel):
    id: str
    node_execution_id: str
    workflow_run_id: str
    description: Optional[str]
    content_to_review: Optional[str]
    status: str
    reviewer_did: Optional[str]
    decision: Optional[str]
    feedback: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]

    @classmethod
    def from_record(cls, g: HumanGateRecord) -> "GateResponse":
        return cls(
            id=g.id,
            node_execution_id=g.node_execution_id,
            workflow_run_id=g.workflow_run_id,
            description=g.description,
            content_to_review=g.content_to_review,
            status=g.status,
            reviewer_did=g.reviewer_did,
            decision=g.decision,
            feedback=g.feedback,
            created_at=g.created_at,
            resolved_at=g.resolved_at,
        )


class GateDecisionRequest(BaseModel):
    reviewer_did: str
    decision: str  # "approved" | "rejected"
    feedback: Optional[str] = None


@router.get("/", response_model=list[GateResponse])
def list_gates(status: Optional[str] = None, db: Session = Depends(get_db)):
    """List all human gates. Filter by status: pending | claimed | approved | rejected."""
    q = db.query(HumanGateRecord)
    if status:
        q = q.filter(HumanGateRecord.status == status)
    return [GateResponse.from_record(g) for g in q.order_by(HumanGateRecord.created_at.desc()).all()]


@router.get("/{gate_id}", response_model=GateResponse)
def get_gate(gate_id: str, db: Session = Depends(get_db)):
    gate = db.query(HumanGateRecord).filter(HumanGateRecord.id == gate_id).first()
    if not gate:
        raise HTTPException(status_code=404, detail="Gate not found")
    return GateResponse.from_record(gate)


@router.post("/{gate_id}/decide", response_model=GateResponse)
def decide_gate(gate_id: str, req: GateDecisionRequest, db: Session = Depends(get_db)):
    """
    Submit a decision on a gate (approved or rejected).
    This resumes or terminates the paused workflow.
    """
    gate = db.query(HumanGateRecord).filter(HumanGateRecord.id == gate_id).first()
    if not gate:
        raise HTTPException(status_code=404, detail="Gate not found")

    if gate.status in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail=f"Gate already {gate.status}")

    if req.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")

    gate.decision = req.decision
    gate.feedback = req.feedback
    gate.reviewer_did = req.reviewer_did
    gate.status = req.decision
    gate.resolved_at = datetime.now(timezone.utc)
    db.commit()

    # Resume workflow
    resume_after_gate(gate, db)
    db.refresh(gate)

    return GateResponse.from_record(gate)
