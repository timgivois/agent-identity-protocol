"""
Pydantic models for request/response validation.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# --- Agent Models ---

class AgentRegisterRequest(BaseModel):
    name: str = Field(..., description="Human-readable name for the agent", example="copywriter-agent-01")
    owner_id: str = Field(..., description="ID of the human owner", example="user_tim_001")


class AgentResponse(BaseModel):
    did: str = Field(..., description="The agent's Decentralized Identifier")
    name: str
    owner_id: str
    public_key_b64: str = Field(..., description="Base64-encoded public key")
    created_at: datetime

    class Config:
        from_attributes = True


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    total: int


# --- Handshake Models ---

class ChallengeRequest(BaseModel):
    requester_did: str = Field(..., description="DID of the agent requesting a challenge")
    target_did: str = Field(..., description="DID of the agent being authenticated against")


class ChallengeResponse(BaseModel):
    nonce: str = Field(..., description="Challenge nonce to be signed")
    requester_did: str
    target_did: str
    expires_in_seconds: int = 300


class VerifyRequest(BaseModel):
    nonce: str = Field(..., description="The challenge nonce")
    requester_did: str = Field(..., description="DID of the agent proving identity")
    signature_b64: str = Field(..., description="Base64-encoded Ed25519 signature of the nonce")


class VerifyResponse(BaseModel):
    verified: bool
    session_token: Optional[str] = None
    agent_did: str
    message: str


# --- DID Document (W3C) ---

class DIDDocument(BaseModel):
    context: list[str] = Field(alias="@context")
    id: str
    controller: str
    verificationMethod: list[dict]
    authentication: list[str]
    assertionMethod: list[str]
    service: list[dict]

    class Config:
        populate_by_name = True
