"""
Workflow builder + execution.
"""
import json
import uuid
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from ..db import get_db, WorkflowRecord, WorkflowRunRecord, NodeExecutionRecord, HumanGateRecord
from ..core.executor import run_workflow

router = APIRouter(prefix="/workflows", tags=["orchestration"])


class NodeConfig(BaseModel):
    role_id: str
    requires_gate: bool = False
    gate_description: Optional[str] = None
    commission_usd: float = 1.0


class WorkflowCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    owner_id: str
    nodes: list[NodeConfig] = Field(..., min_length=1)


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    owner_id: str
    nodes: list[NodeConfig]
    created_at: datetime

    @classmethod
    def from_record(cls, r: WorkflowRecord) -> "WorkflowResponse":
        return cls(
            id=r.id,
            name=r.name,
            description=r.description,
            owner_id=r.owner_id,
            nodes=[NodeConfig(**n) for n in json.loads(r.nodes)],
            created_at=r.created_at,
        )


class NodeExecutionResponse(BaseModel):
    id: str
    role_id: str
    node_index: int
    status: str
    input_data: dict
    output_data: Optional[dict]
    heuristic_passed: Optional[bool]
    heuristic_result: Optional[dict]
    created_at: datetime
    completed_at: Optional[datetime]

    @classmethod
    def from_record(cls, n: NodeExecutionRecord) -> "NodeExecutionResponse":
        return cls(
            id=n.id,
            role_id=n.role_id,
            node_index=n.node_index,
            status=n.status,
            input_data=json.loads(n.input_data or "{}"),
            output_data=json.loads(n.output_data) if n.output_data else None,
            heuristic_passed=n.heuristic_passed,
            heuristic_result=json.loads(n.heuristic_result) if n.heuristic_result else None,
            created_at=n.created_at,
            completed_at=n.completed_at,
        )


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    status: str
    current_node_index: int
    input_data: dict
    output_data: Optional[dict]
    node_executions: list[NodeExecutionResponse]
    pending_gate_id: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]


class RunWorkflowRequest(BaseModel):
    input_data: dict = {}


@router.post("/", response_model=WorkflowResponse, status_code=201)
def create_workflow(req: WorkflowCreateRequest, db: Session = Depends(get_db)):
    """Create a workflow — an ordered chain of roles with optional human gates."""
    wf = WorkflowRecord(
        id=str(uuid.uuid4()),
        name=req.name,
        description=req.description,
        owner_id=req.owner_id,
        nodes=json.dumps([n.model_dump() for n in req.nodes]),
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return WorkflowResponse.from_record(wf)


@router.get("/", response_model=list[WorkflowResponse])
def list_workflows(owner_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(WorkflowRecord)
    if owner_id:
        q = q.filter(WorkflowRecord.owner_id == owner_id)
    return [WorkflowResponse.from_record(w) for w in q.all()]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    wf = db.query(WorkflowRecord).filter(WorkflowRecord.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowResponse.from_record(wf)


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse, status_code=201)
def execute_workflow(workflow_id: str, req: RunWorkflowRequest, db: Session = Depends(get_db)):
    """Start a workflow run. Executes nodes until completion or a human gate."""
    wf = db.query(WorkflowRecord).filter(WorkflowRecord.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run = run_workflow(workflow_id, req.input_data, db)
    db.refresh(run)
    return _build_run_response(run, db)


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)):
    """Get the status of a workflow run."""
    run = db.query(WorkflowRunRecord).filter(WorkflowRunRecord.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _build_run_response(run, db)


def _build_run_response(run: WorkflowRunRecord, db: Session) -> WorkflowRunResponse:
    node_execs = db.query(NodeExecutionRecord).filter(
        NodeExecutionRecord.workflow_run_id == run.id
    ).order_by(NodeExecutionRecord.node_index).all()

    # Check for pending gate
    pending_gate = db.query(HumanGateRecord).filter(
        HumanGateRecord.workflow_run_id == run.id,
        HumanGateRecord.status == "pending",
    ).first()

    return WorkflowRunResponse(
        id=run.id,
        workflow_id=run.workflow_id,
        status=run.status,
        current_node_index=run.current_node_index,
        input_data=json.loads(run.input_data or "{}"),
        output_data=json.loads(run.output_data) if run.output_data else None,
        node_executions=[NodeExecutionResponse.from_record(n) for n in node_execs],
        pending_gate_id=pending_gate.id if pending_gate else None,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )
