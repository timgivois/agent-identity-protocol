"""
Tests for v0.4 Orchestration + v1.0 Marketplace.

Covers:
- Role creation with heuristic config
- Workflow builder (multi-node, with gate)
- Execution engine (passthrough + heuristic validation)
- Human gate flow
- Marketplace: register reviewer, list tasks, claim, complete
- Reputation update after task completion
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app

client = TestClient(app)


# ─── Helpers ──────────────────────────────────────

def register_agent(name="test-agent"):
    r = client.post("/agents/register", json={"name": name, "owner_id": "user_tim"})
    assert r.status_code == 201
    return r.json()


def create_role(name="writer", heuristic_config=None, webhook_url=None):
    payload = {
        "name": name,
        "owner_id": "user_tim",
        "heuristic_config": heuristic_config or {},
    }
    if webhook_url:
        payload["webhook_url"] = webhook_url
    r = client.post("/roles/", json=payload)
    assert r.status_code == 201
    return r.json()


def create_workflow(nodes):
    r = client.post("/workflows/", json={
        "name": "test-workflow",
        "owner_id": "user_tim",
        "nodes": nodes,
    })
    assert r.status_code == 201
    return r.json()


# ─── Role Tests ────────────────────────────────────

class TestRoles:
    def test_create_role(self):
        role = create_role("copywriter")
        assert role["name"] == "copywriter"
        assert "id" in role

    def test_create_role_with_heuristics(self):
        role = create_role("writer", heuristic_config={
            "min_words": 10,
            "required_keywords": ["amazing"],
        })
        assert role["heuristic_config"]["min_words"] == 10

    def test_list_roles(self):
        create_role("r1")
        create_role("r2")
        r = client.get("/roles/")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_get_role(self):
        role = create_role("solo")
        r = client.get(f"/roles/{role['id']}")
        assert r.status_code == 200
        assert r.json()["name"] == "solo"

    def test_delete_role(self):
        role = create_role("delete-me")
        r = client.delete(f"/roles/{role['id']}")
        assert r.status_code == 204
        r = client.get(f"/roles/{role['id']}")
        assert r.status_code == 404


# ─── Heuristic Tests ──────────────────────────────

class TestHeuristics:
    def test_passthrough_no_heuristics(self):
        """Workflow with no heuristics completes immediately."""
        role = create_role("passthrough")
        wf = create_workflow([{"role_id": role["id"], "requires_gate": False}])
        r = client.post(f"/workflows/{wf['id']}/run", json={"input_data": {"text": "hello world"}})
        assert r.status_code == 201
        run = r.json()
        assert run["status"] == "completed"

    def test_word_count_heuristic_passes(self):
        """Output with enough words passes the heuristic."""
        role = create_role("writer", heuristic_config={"min_words": 3})
        wf = create_workflow([{"role_id": role["id"], "requires_gate": False}])
        r = client.post(f"/workflows/{wf['id']}/run",
                        json={"input_data": {"output": "this has four words"}})
        assert r.status_code == 201
        run = r.json()
        assert run["status"] == "completed"
        node = run["node_executions"][0]
        assert node["heuristic_passed"] is True

    def test_word_count_heuristic_fails(self):
        """Output with too few words fails and stops the workflow."""
        role = create_role("strict", heuristic_config={"min_words": 100})
        wf = create_workflow([{"role_id": role["id"], "requires_gate": False}])
        r = client.post(f"/workflows/{wf['id']}/run",
                        json={"input_data": {"output": "too short"}})
        assert r.status_code == 201
        run = r.json()
        assert run["status"] == "failed"
        node = run["node_executions"][0]
        assert node["heuristic_passed"] is False

    def test_required_keywords_pass(self):
        role = create_role("brand", heuristic_config={"required_keywords": ["amazing"]})
        wf = create_workflow([{"role_id": role["id"]}])
        r = client.post(f"/workflows/{wf['id']}/run",
                        json={"input_data": {"output": "this product is amazing and great"}})
        run = r.json()
        assert run["node_executions"][0]["heuristic_passed"] is True

    def test_required_keywords_fail(self):
        role = create_role("brand", heuristic_config={"required_keywords": ["amazing", "brand"]})
        wf = create_workflow([{"role_id": role["id"]}])
        r = client.post(f"/workflows/{wf['id']}/run",
                        json={"input_data": {"output": "this is mediocre content"}})
        run = r.json()
        assert run["node_executions"][0]["heuristic_passed"] is False

    def test_forbidden_keywords_fail(self):
        role = create_role("clean", heuristic_config={"forbidden_keywords": ["competitor"]})
        wf = create_workflow([{"role_id": role["id"]}])
        r = client.post(f"/workflows/{wf['id']}/run",
                        json={"input_data": {"output": "better than competitor X"}})
        run = r.json()
        assert run["node_executions"][0]["heuristic_passed"] is False


# ─── Human Gate Tests ──────────────────────────────

class TestHumanGates:
    def test_gate_pauses_workflow(self):
        """Workflow with a gate pauses instead of completing."""
        role = create_role("gated")
        wf = create_workflow([{
            "role_id": role["id"],
            "requires_gate": True,
            "gate_description": "Review the output",
        }])
        r = client.post(f"/workflows/{wf['id']}/run",
                        json={"input_data": {"output": "some content to review"}})
        run = r.json()
        assert run["status"] == "paused"
        assert run["pending_gate_id"] is not None

    def test_gate_approve_resumes_workflow(self):
        """Approving a gate resumes and completes the workflow."""
        role = create_role("gated")
        wf = create_workflow([{
            "role_id": role["id"],
            "requires_gate": True,
            "gate_description": "Review me",
        }])
        run_r = client.post(f"/workflows/{wf['id']}/run",
                            json={"input_data": {"output": "content"}})
        run = run_r.json()
        gate_id = run["pending_gate_id"]

        # Approve
        dec_r = client.post(f"/gates/{gate_id}/decide", json={
            "reviewer_did": "did:agent:test",
            "decision": "approved",
            "feedback": "Looks good!",
        })
        assert dec_r.status_code == 200
        assert dec_r.json()["decision"] == "approved"

        # Check run completed
        run_status = client.get(f"/workflows/runs/{run['id']}").json()
        assert run_status["status"] == "completed"

    def test_gate_reject_fails_workflow(self):
        """Rejecting a gate fails the workflow."""
        role = create_role("gated")
        wf = create_workflow([{
            "role_id": role["id"],
            "requires_gate": True,
        }])
        run_r = client.post(f"/workflows/{wf['id']}/run",
                            json={"input_data": {"output": "bad content"}})
        run = run_r.json()
        gate_id = run["pending_gate_id"]

        client.post(f"/gates/{gate_id}/decide", json={
            "reviewer_did": "did:agent:test",
            "decision": "rejected",
            "feedback": "Does not meet standards.",
        })

        run_status = client.get(f"/workflows/runs/{run['id']}").json()
        assert run_status["status"] == "failed"

    def test_multi_node_with_gate_in_middle(self):
        """3-node workflow: node1 → gate → node3. Gate in middle pauses, approve resumes."""
        role = create_role("node1")
        role2 = create_role("node2-gated")
        role3 = create_role("node3")

        wf = create_workflow([
            {"role_id": role["id"], "requires_gate": False},
            {"role_id": role2["id"], "requires_gate": True, "gate_description": "middle gate"},
            {"role_id": role3["id"], "requires_gate": False},
        ])
        run_r = client.post(f"/workflows/{wf['id']}/run",
                            json={"input_data": {"output": "initial"}})
        run = run_r.json()
        assert run["status"] == "paused"
        assert run["current_node_index"] == 1  # paused at node 2

        gate_id = run["pending_gate_id"]
        client.post(f"/gates/{gate_id}/decide", json={
            "reviewer_did": "did:agent:test",
            "decision": "approved",
        })

        run_status = client.get(f"/workflows/runs/{run['id']}").json()
        assert run_status["status"] == "completed"


# ─── Marketplace Tests ─────────────────────────────

class TestMarketplace:
    def test_register_reviewer(self):
        """Reviewer must have a valid DID."""
        agent = register_agent("reviewer-human")
        r = client.post("/marketplace/reviewers", json={
            "did": agent["did"],
            "display_name": "Alice the Reviewer",
            "specializations": ["copywriting", "UX"],
        })
        assert r.status_code == 201
        data = r.json()
        assert data["display_name"] == "Alice the Reviewer"
        assert data["reputation_score"] == 0.0
        assert data["tasks_completed"] == 0

    def test_register_reviewer_without_did_fails(self):
        """Cannot register with a DID that doesn't exist."""
        r = client.post("/marketplace/reviewers", json={
            "did": "did:agent:nonexistent",
            "display_name": "Ghost",
        })
        assert r.status_code == 400

    def test_duplicate_reviewer_rejected(self):
        agent = register_agent()
        client.post("/marketplace/reviewers", json={"did": agent["did"], "display_name": "Alice"})
        r = client.post("/marketplace/reviewers", json={"did": agent["did"], "display_name": "Alice2"})
        assert r.status_code == 409

    def test_task_created_on_gate(self):
        """When a gate is created, a marketplace task appears automatically."""
        role = create_role("gated-role")
        wf = create_workflow([{
            "role_id": role["id"],
            "requires_gate": True,
            "gate_description": "Review copy",
            "commission_usd": 2.50,
        }])
        client.post(f"/workflows/{wf['id']}/run", json={"input_data": {"output": "review me"}})

        tasks = client.get("/marketplace/tasks?status=open").json()
        assert len(tasks) == 1
        assert tasks[0]["commission_usd"] == 2.50
        assert tasks[0]["status"] == "open"

    def test_full_marketplace_flow(self):
        """Full flow: gate created → reviewer claims → completes → reputation updated."""
        # Setup
        reviewer_agent = register_agent("reviewer")
        client.post("/marketplace/reviewers", json={
            "did": reviewer_agent["did"],
            "display_name": "Alice",
            "specializations": ["copywriting"],
        })

        role = create_role("writer-role")
        wf = create_workflow([{
            "role_id": role["id"],
            "requires_gate": True,
            "commission_usd": 5.0,
        }])
        run_r = client.post(f"/workflows/{wf['id']}/run",
                            json={"input_data": {"output": "great content for review"}})
        run = run_r.json()
        assert run["status"] == "paused"

        # Claim task
        tasks = client.get("/marketplace/tasks?status=open").json()
        task_id = tasks[0]["id"]
        claimed = client.post(f"/marketplace/tasks/{task_id}/claim", json={
            "reviewer_did": reviewer_agent["did"],
        })
        assert claimed.status_code == 200
        assert claimed.json()["status"] == "claimed"

        # Complete task
        completed = client.post(f"/marketplace/tasks/{task_id}/complete", json={
            "reviewer_did": reviewer_agent["did"],
            "decision": "approved",
            "feedback": "Excellent quality!",
        })
        assert completed.status_code == 200
        assert completed.json()["decision"] == "approved"

        # Verify reviewer stats updated
        reviewer = client.get(f"/marketplace/reviewers/{reviewer_agent['did']}").json()
        assert reviewer["tasks_completed"] == 1
        assert reviewer["total_earned"] == 5.0
        assert reviewer["reputation_score"] > 0

        # Verify workflow completed
        run_status = client.get(f"/workflows/runs/{run['id']}").json()
        assert run_status["status"] == "completed"

    def test_leaderboard(self):
        """Leaderboard ranks reviewers by reputation."""
        a1 = register_agent("rev1")
        a2 = register_agent("rev2")
        client.post("/marketplace/reviewers", json={"did": a1["did"], "display_name": "Alice"})
        client.post("/marketplace/reviewers", json={"did": a2["did"], "display_name": "Bob"})

        lb = client.get("/marketplace/leaderboard").json()
        assert len(lb) == 2
        assert lb[0]["rank"] == 1

    def test_marketplace_stats(self):
        stats = client.get("/marketplace/stats").json()
        assert "reviewers" in stats
        assert "tasks" in stats
        assert "total_commission_paid_usd" in stats
