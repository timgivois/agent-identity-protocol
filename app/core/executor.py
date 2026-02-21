"""
Workflow execution engine.

Flow for each node:
  1. Get role definition
  2. Call role's webhook (POST with input_data) — or use passthrough if no webhook
  3. Run heuristic validators on output
  4. If heuristics fail → mark node as failed, stop workflow
  5. If role requires_gate → create HumanGate, pause workflow
  6. If no gate → mark node completed, advance to next node
  7. Repeat until workflow completes or pauses

"Bring your own agent" model:
  - Roles define a webhook_url
  - The engine POSTs input_data to that URL and expects {"output": "..."}
  - If no webhook → output = input (passthrough, useful for testing)
"""
import json
import uuid
import httpx
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from ..db import (
    WorkflowRunRecord, NodeExecutionRecord, HumanGateRecord,
    RoleRecord, WorkflowRecord, ReviewTaskRecord
)
from .validators import run_heuristics


def _now():
    return datetime.now(timezone.utc)


def _call_webhook(webhook_url: str, input_data: dict) -> dict:
    """
    POST input_data to the role's webhook URL.
    Expects JSON response with at least {"output": "<text>"}.
    Times out after 30s.
    """
    try:
        resp = httpx.post(webhook_url, json=input_data, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"output": f"[webhook error: {e}]", "error": str(e)}


def _execute_role(role: RoleRecord, input_data: dict) -> dict:
    """Execute a role — call webhook or passthrough."""
    if role.webhook_url:
        return _call_webhook(role.webhook_url, input_data)
    # Passthrough: output = input (no webhook configured)
    return {"output": json.dumps(input_data), "passthrough": True}


def run_workflow(workflow_id: str, input_data: dict, db: Session) -> WorkflowRunRecord:
    """
    Create and start a new workflow run.
    Returns immediately — execution is synchronous per node until a gate is hit.
    """
    workflow = db.query(WorkflowRecord).filter(WorkflowRecord.id == workflow_id).first()
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")

    nodes = json.loads(workflow.nodes)

    run = WorkflowRunRecord(
        id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        status="running",
        current_node_index=0,
        input_data=json.dumps(input_data),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    _advance_run(run, nodes, input_data, db)
    return run


def _advance_run(run: WorkflowRunRecord, nodes: list, current_input: dict, db: Session):
    """
    Execute nodes sequentially from current_node_index until:
    - A gate is hit (pause)
    - All nodes complete (done)
    - A node fails (fail)
    """
    while run.current_node_index < len(nodes):
        node_config = nodes[run.current_node_index]
        role_id = node_config["role_id"]
        role = db.query(RoleRecord).filter(RoleRecord.id == role_id).first()

        if not role:
            run.status = "failed"
            db.commit()
            return

        # Create node execution record
        node_exec = NodeExecutionRecord(
            id=str(uuid.uuid4()),
            workflow_run_id=run.id,
            role_id=role_id,
            node_index=run.current_node_index,
            status="running",
            input_data=json.dumps(current_input),
        )
        db.add(node_exec)
        db.commit()

        # Execute role
        result = _execute_role(role, current_input)
        output_text = result.get("output", "")
        output_data = {"output": output_text, "raw": result}

        node_exec.output_data = json.dumps(output_data)

        # Run heuristics
        heuristic_config = json.loads(role.heuristic_config or "{}")
        validation = run_heuristics(output_text, heuristic_config)
        node_exec.heuristic_passed = validation.passed
        node_exec.heuristic_result = json.dumps(validation.to_dict())

        if not validation.passed:
            # Heuristic failed — stop here
            node_exec.status = "failed"
            node_exec.completed_at = _now()
            run.status = "failed"
            db.commit()
            return

        # Check if gate required
        requires_gate = node_config.get("requires_gate", False)
        if requires_gate:
            # Create human gate
            gate = HumanGateRecord(
                id=str(uuid.uuid4()),
                node_execution_id=node_exec.id,
                workflow_run_id=run.id,
                description=node_config.get("gate_description", "Review required"),
                content_to_review=output_text,
                status="pending",
            )
            db.add(gate)

            # Create marketplace review task
            task = ReviewTaskRecord(
                id=str(uuid.uuid4()),
                gate_id=gate.id,
                commission_usd=node_config.get("commission_usd", 1.0),
                status="open",
            )
            db.add(task)

            node_exec.status = "awaiting_gate"
            run.status = "paused"
            db.commit()
            return  # Pause — will resume when gate is resolved

        # Node complete — pass output as next node's input
        node_exec.status = "completed"
        node_exec.completed_at = _now()
        current_input = {"output": output_text, "node_index": run.current_node_index}
        run.current_node_index += 1
        db.commit()

    # All nodes done
    run.status = "completed"
    run.output_data = json.dumps(current_input)
    run.completed_at = _now()
    db.commit()


def resume_after_gate(gate: HumanGateRecord, db: Session):
    """
    Called after a human gate is approved.
    Resumes the workflow from the next node.
    """
    if gate.decision != "approved":
        # Rejected — mark run as failed
        run = db.query(WorkflowRunRecord).filter(
            WorkflowRunRecord.id == gate.workflow_run_id
        ).first()
        if run:
            run.status = "failed"
            db.commit()
        return

    run = db.query(WorkflowRunRecord).filter(
        WorkflowRunRecord.id == gate.workflow_run_id
    ).first()
    if not run:
        return

    workflow = db.query(WorkflowRecord).filter(WorkflowRecord.id == run.workflow_id).first()
    nodes = json.loads(workflow.nodes)

    # Get the node execution that was paused
    node_exec = db.query(NodeExecutionRecord).filter(
        NodeExecutionRecord.id == gate.node_execution_id
    ).first()
    node_exec.status = "approved"
    node_exec.completed_at = _now()

    # Advance past this node
    run.current_node_index += 1
    run.status = "running"
    db.commit()

    # Continue from the next node, using gate's approved content as input
    next_input = {
        "output": gate.content_to_review,
        "gate_feedback": gate.feedback,
        "node_index": run.current_node_index - 1,
    }
    _advance_run(run, nodes, next_input, db)
