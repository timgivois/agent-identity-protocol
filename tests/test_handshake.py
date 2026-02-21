"""
Tests for the Agent Identity Protocol handshake flow.
"""
import base64
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import AgentRecord
from app.core.crypto import (
    generate_keypair, sign_message,
    encrypt_private_key, public_bytes_to_b64
)
from app.config import settings

# Use same DB as conftest
_engine = create_engine("sqlite:///./test_shared.db", connect_args={"check_same_thread": False})
_Session = sessionmaker(bind=_engine)

client = TestClient(app)


class TestAgentRegistration:
    def test_register_agent(self):
        r = client.post("/agents/register", json={"name": "test-agent", "owner_id": "user_tim"})
        assert r.status_code == 201
        data = r.json()
        assert data["did"].startswith("did:agent:")
        assert data["name"] == "test-agent"

    def test_list_agents(self):
        client.post("/agents/register", json={"name": "agent-1", "owner_id": "user_1"})
        client.post("/agents/register", json={"name": "agent-2", "owner_id": "user_1"})
        r = client.get("/agents/")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2

    def test_get_agent_by_did(self):
        reg = client.post("/agents/register", json={"name": "test-agent", "owner_id": "user_1"})
        did = reg.json()["did"]
        r = client.get(f"/agents/{did}")
        assert r.status_code == 200
        assert r.json()["did"] == did

    def test_get_nonexistent_agent(self):
        r = client.get("/agents/did:agent:nonexistent")
        assert r.status_code == 404


class TestDIDDocument:
    def test_resolve_did_document(self):
        reg = client.post("/agents/register", json={"name": "test-agent", "owner_id": "user_1"})
        did = reg.json()["did"]
        r = client.get(f"/.well-known/did/{did}")
        assert r.status_code == 200
        doc = r.json()
        assert doc["id"] == did
        assert doc["verificationMethod"][0]["type"] == "Ed25519VerificationKey2020"


class TestHandshakeProtocol:
    def _register_agent(self, name: str) -> dict:
        r = client.post("/agents/register", json={"name": name, "owner_id": "user_tim"})
        assert r.status_code == 201
        return r.json()

    def _patch_agent_keys(self, did: str, private_bytes: bytes, public_bytes: bytes):
        """Swap agent's keys with a known keypair so tests can sign."""
        db = _Session()
        record = db.query(AgentRecord).filter(AgentRecord.did == did).first()
        record.public_key_b64 = public_bytes_to_b64(public_bytes)
        record.encrypted_private_key = encrypt_private_key(private_bytes, settings.master_secret)
        db.commit()
        db.close()

    def test_full_handshake_flow(self):
        """Full handshake: register → challenge → sign → verify → JWT token."""
        agent_a = self._register_agent("agent-a")
        agent_b = self._register_agent("agent-b")
        did_a = agent_a["did"]
        did_b = agent_b["did"]

        # Request challenge
        challenge_resp = client.post("/handshake/challenge", json={
            "requester_did": did_a, "target_did": did_b,
        })
        assert challenge_resp.status_code == 200
        nonce = challenge_resp.json()["nonce"]
        assert len(nonce) == 64

        # Patch keys + sign
        private_bytes, public_bytes = generate_keypair()
        self._patch_agent_keys(did_a, private_bytes, public_bytes)
        sig_bytes = sign_message(private_bytes, nonce.encode())
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

        # Verify
        r = client.post("/handshake/verify", json={
            "nonce": nonce,
            "requester_did": did_a,
            "signature_b64": sig_b64,
        })
        assert r.status_code == 200
        result = r.json()
        assert result["verified"] is True
        assert result["session_token"] is not None
        assert result["agent_did"] == did_a

    def test_invalid_signature_rejected(self):
        agent_a = self._register_agent("agent-a")
        agent_b = self._register_agent("agent-b")

        challenge_resp = client.post("/handshake/challenge", json={
            "requester_did": agent_a["did"], "target_did": agent_b["did"],
        })
        nonce = challenge_resp.json()["nonce"]

        wrong_private, _ = generate_keypair()
        sig_bytes = sign_message(wrong_private, nonce.encode())
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

        r = client.post("/handshake/verify", json={
            "nonce": nonce,
            "requester_did": agent_a["did"],
            "signature_b64": sig_b64,
        })
        assert r.status_code == 200
        assert r.json()["verified"] is False

    def test_replay_attack_prevented(self):
        agent_a = self._register_agent("agent-a")
        agent_b = self._register_agent("agent-b")

        challenge_resp = client.post("/handshake/challenge", json={
            "requester_did": agent_a["did"], "target_did": agent_b["did"],
        })
        nonce = challenge_resp.json()["nonce"]

        private_bytes, public_bytes = generate_keypair()
        self._patch_agent_keys(agent_a["did"], private_bytes, public_bytes)
        sig_bytes = sign_message(private_bytes, nonce.encode())
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

        # First use — success
        r1 = client.post("/handshake/verify", json={
            "nonce": nonce, "requester_did": agent_a["did"], "signature_b64": sig_b64,
        })
        assert r1.json()["verified"] is True

        # Second use — blocked
        r2 = client.post("/handshake/verify", json={
            "nonce": nonce, "requester_did": agent_a["did"], "signature_b64": sig_b64,
        })
        assert r2.status_code == 400
        assert "already used" in r2.json()["detail"]
