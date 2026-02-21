"""
Tests for the Agent Identity Protocol handshake flow.

Tests:
1. Register two agents
2. Request a challenge from agent A targeting agent B
3. Sign the challenge with agent A's private key
4. Verify the signature and get a session token
5. Assert token is valid
6. Replay attack prevention
"""
import base64
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, get_db
from app.core.crypto import (
    generate_keypair, decrypt_private_key, sign_message,
    encrypt_private_key, public_bytes_to_b64
)
from app.core.did import public_key_to_did
from app.config import settings

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///./test_agent_identity.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

# Create tables before tests
Base.metadata.create_all(bind=engine)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    """Clean the database before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


class TestAgentRegistration:
    def test_register_agent(self):
        response = client.post("/agents/register", json={
            "name": "test-agent",
            "owner_id": "user_tim_001"
        })
        assert response.status_code == 201
        data = response.json()
        assert data["did"].startswith("did:agent:")
        assert data["name"] == "test-agent"
        assert data["owner_id"] == "user_tim_001"
        assert "public_key_b64" in data

    def test_list_agents(self):
        client.post("/agents/register", json={"name": "agent-1", "owner_id": "user_1"})
        client.post("/agents/register", json={"name": "agent-2", "owner_id": "user_1"})
        response = client.get("/agents/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["agents"]) == 2

    def test_get_agent_by_did(self):
        reg = client.post("/agents/register", json={"name": "test-agent", "owner_id": "user_1"})
        did = reg.json()["did"]
        response = client.get(f"/agents/{did}")
        assert response.status_code == 200
        assert response.json()["did"] == did

    def test_get_nonexistent_agent(self):
        response = client.get("/agents/did:agent:nonexistent")
        assert response.status_code == 404


class TestDIDDocument:
    def test_resolve_did_document(self):
        reg = client.post("/agents/register", json={"name": "test-agent", "owner_id": "user_1"})
        did = reg.json()["did"]
        response = client.get(f"/.well-known/did/{did}")
        assert response.status_code == 200
        doc = response.json()
        assert doc["id"] == did
        assert len(doc["verificationMethod"]) == 1
        assert doc["verificationMethod"][0]["type"] == "Ed25519VerificationKey2020"


class TestHandshakeProtocol:
    """Core handshake tests — this is the heart of the protocol."""

    def _register_agent(self, name: str, owner_id: str = "user_tim") -> dict:
        response = client.post("/agents/register", json={"name": name, "owner_id": owner_id})
        assert response.status_code == 201
        return response.json()

    def test_full_handshake_flow(self):
        """
        Full handshake: register agents → challenge → sign → verify → JWT token.
        """
        # 1. Register two agents
        agent_a = self._register_agent("agent-a")
        agent_b = self._register_agent("agent-b")

        did_a = agent_a["did"]
        did_b = agent_b["did"]

        # 2. Agent A requests a challenge
        challenge_resp = client.post("/handshake/challenge", json={
            "requester_did": did_a,
            "target_did": did_b,
        })
        assert challenge_resp.status_code == 200
        nonce = challenge_resp.json()["nonce"]
        assert len(nonce) == 64  # 32 bytes hex = 64 chars

        # 3. Sign the nonce with Agent A's private key
        # (In production, only the agent itself holds the private key)
        # For testing, we generate a fresh keypair and use that
        private_bytes, public_bytes = generate_keypair()
        did_test = public_key_to_did(public_bytes)

        # Register agent with known keypair so we can sign
        from app.db import AgentRecord
        from sqlalchemy.orm import Session
        db = TestSessionLocal()
        agent_record = db.query(AgentRecord).filter(AgentRecord.did == did_a).first()

        # Replace the agent's keys with our known test keys
        agent_record.public_key_b64 = public_bytes_to_b64(public_bytes)
        agent_record.encrypted_private_key = encrypt_private_key(private_bytes, settings.master_secret)
        db.commit()
        db.close()

        # Now sign the nonce
        nonce_bytes = nonce.encode("utf-8")
        signature_bytes = sign_message(private_bytes, nonce_bytes)
        signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode().rstrip("=")

        # 4. Verify the signature
        verify_resp = client.post("/handshake/verify", json={
            "nonce": nonce,
            "requester_did": did_a,
            "signature_b64": signature_b64,
        })
        assert verify_resp.status_code == 200
        result = verify_resp.json()

        # 5. Assert verification succeeded and token issued
        assert result["verified"] is True
        assert result["session_token"] is not None
        assert result["agent_did"] == did_a
        print(f"✅ Handshake successful! Token: {result['session_token'][:30]}...")

    def test_invalid_signature_rejected(self):
        """Wrong signature should fail verification."""
        agent_a = self._register_agent("agent-a")
        agent_b = self._register_agent("agent-b")

        challenge_resp = client.post("/handshake/challenge", json={
            "requester_did": agent_a["did"],
            "target_did": agent_b["did"],
        })
        nonce = challenge_resp.json()["nonce"]

        # Sign with a DIFFERENT private key (wrong agent)
        wrong_private, _ = generate_keypair()
        signature_bytes = sign_message(wrong_private, nonce.encode())
        signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode().rstrip("=")

        verify_resp = client.post("/handshake/verify", json={
            "nonce": nonce,
            "requester_did": agent_a["did"],
            "signature_b64": signature_b64,
        })
        assert verify_resp.status_code == 200
        assert verify_resp.json()["verified"] is False

    def test_replay_attack_prevented(self):
        """Same nonce cannot be used twice."""
        agent_a = self._register_agent("agent-a")
        agent_b = self._register_agent("agent-b")

        # Get challenge
        challenge_resp = client.post("/handshake/challenge", json={
            "requester_did": agent_a["did"],
            "target_did": agent_b["did"],
        })
        nonce = challenge_resp.json()["nonce"]

        # Set up known keys
        private_bytes, public_bytes = generate_keypair()
        from app.db import AgentRecord
        db = TestSessionLocal()
        agent_record = db.query(AgentRecord).filter(AgentRecord.did == agent_a["did"]).first()
        agent_record.public_key_b64 = public_bytes_to_b64(public_bytes)
        agent_record.encrypted_private_key = encrypt_private_key(private_bytes, settings.master_secret)
        db.commit()
        db.close()

        signature_bytes = sign_message(private_bytes, nonce.encode())
        signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode().rstrip("=")

        # First use — should succeed
        r1 = client.post("/handshake/verify", json={
            "nonce": nonce,
            "requester_did": agent_a["did"],
            "signature_b64": signature_b64,
        })
        assert r1.json()["verified"] is True

        # Second use — should fail (replay attack)
        r2 = client.post("/handshake/verify", json={
            "nonce": nonce,
            "requester_did": agent_a["did"],
            "signature_b64": signature_b64,
        })
        assert r2.status_code == 400
        assert "already used" in r2.json()["detail"]
