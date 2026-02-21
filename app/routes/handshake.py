"""
Agent-to-agent handshake protocol.

Flow:
1. Agent A calls POST /handshake/challenge with its DID and target DID
2. Server returns a nonce (random challenge)
3. Agent A signs the nonce with its Ed25519 private key
4. Agent A calls POST /handshake/verify with the nonce + signature
5. Server verifies signature using Agent A's public key (from its DID record)
6. If valid, server returns a JWT session token

This proves: "I am the agent who controls this DID"
"""
import base64
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from jose import jwt

from ..db import get_db, AgentRecord, ChallengeRecord
from ..models import ChallengeRequest, ChallengeResponse, VerifyRequest, VerifyResponse
from ..core.crypto import verify_signature, b64_to_public_bytes
from ..config import settings

router = APIRouter(prefix="/handshake", tags=["handshake"])

NONCE_EXPIRY_SECONDS = 300  # 5 minutes
JWT_EXPIRY_HOURS = 24


def _get_agent_or_404(did: str, db: Session) -> AgentRecord:
    agent = db.query(AgentRecord).filter(AgentRecord.did == did).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {did}")
    return agent


@router.post("/challenge", response_model=ChallengeResponse)
def request_challenge(request: ChallengeRequest, db: Session = Depends(get_db)):
    """
    Step 1: Request a challenge nonce.
    Agent A wants to prove its identity to Agent B (or the system).
    Returns a nonce that Agent A must sign with its private key.
    """
    # Validate both agents exist
    _get_agent_or_404(request.requester_did, db)
    _get_agent_or_404(request.target_did, db)

    # Generate a cryptographically secure nonce
    nonce = secrets.token_hex(32)

    # Store the challenge
    challenge = ChallengeRecord(
        nonce=nonce,
        requester_did=request.requester_did,
        target_did=request.target_did,
    )
    db.add(challenge)
    db.commit()

    return ChallengeResponse(
        nonce=nonce,
        requester_did=request.requester_did,
        target_did=request.target_did,
        expires_in_seconds=NONCE_EXPIRY_SECONDS,
    )


@router.post("/verify", response_model=VerifyResponse)
def verify_challenge(request: VerifyRequest, db: Session = Depends(get_db)):
    """
    Step 2: Verify a signed challenge.
    Agent A provides its DID, the nonce, and the nonce signed with its private key.
    Server verifies the signature and issues a JWT session token if valid.
    """
    # Find the challenge
    challenge = db.query(ChallengeRecord).filter(
        ChallengeRecord.nonce == request.nonce,
        ChallengeRecord.requester_did == request.requester_did,
    ).first()

    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    # Check if already used (replay attack prevention)
    if challenge.used == "true":
        raise HTTPException(status_code=400, detail="Challenge already used")

    # Check expiry
    created_at = challenge.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created_at).total_seconds()
    if age > NONCE_EXPIRY_SECONDS:
        raise HTTPException(status_code=400, detail="Challenge expired")

    # Get requester's public key
    agent = _get_agent_or_404(request.requester_did, db)
    public_bytes = b64_to_public_bytes(agent.public_key_b64)

    # Decode signature
    try:
        # Add padding if needed
        sig_b64 = request.signature_b64
        padding = 4 - len(sig_b64) % 4
        if padding != 4:
            sig_b64 += "=" * padding
        signature_bytes = base64.urlsafe_b64decode(sig_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature encoding")

    # Verify signature
    nonce_bytes = request.nonce.encode("utf-8")
    is_valid = verify_signature(public_bytes, nonce_bytes, signature_bytes)

    if not is_valid:
        return VerifyResponse(
            verified=False,
            agent_did=request.requester_did,
            message="Signature verification failed",
        )

    # Mark challenge as used
    challenge.used = "true"
    db.commit()

    # Issue JWT session token
    payload = {
        "sub": request.requester_did,
        "iss": "did:agent:protocol",
        "iat": datetime.now(timezone.utc).timestamp(),
        "exp": (datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp(),
        "scope": "agent:authenticated",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

    return VerifyResponse(
        verified=True,
        session_token=token,
        agent_did=request.requester_did,
        message="Identity verified. Session token issued.",
    )
