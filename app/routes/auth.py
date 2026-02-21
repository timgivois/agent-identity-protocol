"""
Auth endpoints.

Agent flow:
  POST /auth/agents/register  → {api_key, claim_url, did}
  GET  /auth/agents/status    → {status: pending|claimed}
  POST /auth/agents/rotate    → {api_key} (new key)

Human flow:
  POST /auth/signup           → sends magic link
  POST /auth/login            → sends magic link
  GET  /auth/verify           → consumes token → sets JWT cookie
  GET  /auth/me               → current user info
  POST /auth/claim/{token}    → claim an agent after login
"""
import uuid
import json
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from ..db import (
    get_db, AgentRecord, UserRecord, AgentClaimRecord,
    ApiKeyRecord, MagicLinkRecord
)
from ..auth import (
    create_api_key_record, create_magic_link, resolve_magic_link,
    create_jwt, get_current_agent, get_current_user
)
from ..core.crypto import generate_keypair, encrypt_private_key, public_bytes_to_b64
from ..core.did import public_key_to_did
from ..core.email import send_magic_link
from ..config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


# ─── Agent Registration ────────────────────────────

class AgentRegisterRequest(BaseModel):
    name: str
    description: Optional[str] = None


class AgentRegisterResponse(BaseModel):
    did: str
    name: str
    api_key: str
    claim_url: str
    important: str = "⚠️ Save your API key! It won't be shown again."


@router.post("/agents/register", response_model=AgentRegisterResponse, status_code=201)
def register_agent(req: AgentRegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new AI agent.
    Returns an API key (shown once!) and a claim URL for the human owner.
    """
    # Generate identity
    private_bytes, public_bytes = generate_keypair()
    did = public_key_to_did(public_bytes)

    # Check collision
    if db.query(AgentRecord).filter(AgentRecord.did == did).first():
        raise HTTPException(status_code=409, detail="DID collision — try again")

    # Create agent
    agent = AgentRecord(
        did=did,
        name=req.name,
        description=req.description,
        owner_id="unclaimed",  # updated on claim
        public_key_b64=public_bytes_to_b64(public_bytes),
        encrypted_private_key=encrypt_private_key(private_bytes, settings.master_secret),
    )
    db.add(agent)

    # Create claim record
    import secrets
    claim_token = f"claim_{secrets.token_urlsafe(24)}"
    claim = AgentClaimRecord(
        id=str(uuid.uuid4()),
        agent_did=did,
        claim_token=claim_token,
        status="pending",
    )
    db.add(claim)

    # Generate API key
    raw_key, _ = create_api_key_record(did, db)

    db.commit()

    return AgentRegisterResponse(
        did=did,
        name=req.name,
        api_key=raw_key,
        claim_url=f"{settings.frontend_url}/claim/{claim_token}",
    )


@router.get("/agents/status")
async def agent_status(agent: AgentRecord = Depends(get_current_agent), db: Session = Depends(get_db)):
    """Check if your agent has been claimed by a human."""
    claim = db.query(AgentClaimRecord).filter(AgentClaimRecord.agent_did == agent.did).first()
    return {
        "did": agent.did,
        "name": agent.name,
        "is_claimed": agent.is_claimed,
        "status": "claimed" if agent.is_claimed else "pending_claim",
    }


@router.get("/agents/me")
async def agent_me(agent: AgentRecord = Depends(get_current_agent)):
    """Get your agent profile."""
    return {
        "did": agent.did,
        "name": agent.name,
        "description": agent.description,
        "is_claimed": agent.is_claimed,
        "is_active": agent.is_active,
        "created_at": agent.created_at,
    }


@router.post("/agents/rotate")
async def rotate_api_key(
    agent: AgentRecord = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Rotate API key. Old key is immediately revoked."""
    # Revoke all current keys
    db.query(ApiKeyRecord).filter(
        ApiKeyRecord.agent_did == agent.did,
        ApiKeyRecord.revoked == False,
    ).update({"revoked": True})
    db.commit()

    raw_key, _ = create_api_key_record(agent.did, db)
    return {
        "api_key": raw_key,
        "important": "⚠️ Save your new API key! Your old key has been revoked.",
    }


# ─── Human Auth ────────────────────────────────────

class EmailRequest(BaseModel):
    email: str


@router.post("/signup")
def signup(req: EmailRequest, db: Session = Depends(get_db)):
    """
    Create an account or log in (magic link sent either way).
    If account exists → login link. If new → signup link.
    """
    existing = db.query(UserRecord).filter(UserRecord.email == req.email).first()
    purpose = "login" if existing else "verify"

    if not existing:
        # Create unverified user
        user = UserRecord(id=str(uuid.uuid4()), email=req.email)
        db.add(user)
        db.commit()

    token = create_magic_link(req.email, purpose, db)
    send_magic_link(req.email, token, purpose)

    return {"message": "Magic link sent! Check your email.", "email": req.email}


@router.post("/login")
def login(req: EmailRequest, db: Session = Depends(get_db)):
    """Send a magic login link."""
    user = db.query(UserRecord).filter(UserRecord.email == req.email).first()
    if not user:
        # Don't leak whether email exists — send generic message
        return {"message": "If this email is registered, you'll receive a login link."}

    token = create_magic_link(req.email, "login", db)
    send_magic_link(req.email, token, "login")
    return {"message": "Magic link sent! Check your email."}


@router.get("/verify")
def verify_magic_link(
    token: str = Query(...),
    purpose: str = Query("login"),
    response: Response = None,
    db: Session = Depends(get_db),
):
    """
    Consume a magic link token.
    Returns a JWT session token + sets cookie.
    """
    record = resolve_magic_link(token, db)
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired link")

    # Get or create user
    user = db.query(UserRecord).filter(UserRecord.email == record.email).first()
    if not user:
        user = UserRecord(id=str(uuid.uuid4()), email=record.email)
        db.add(user)

    user.email_verified = True
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    jwt_token = create_jwt(user.id, user.email, user.role)

    # Set cookie
    response.set_cookie(
        key="session_token",
        value=jwt_token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=60 * 60 * 24 * 7,
    )

    return {
        "session_token": jwt_token,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
        },
        "message": "Logged in successfully!",
    }


@router.get("/me")
async def me(user: UserRecord = Depends(get_current_user)):
    """Get current human user profile."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "email_verified": user.email_verified,
        "x_handle": user.x_handle,
        "created_at": user.created_at,
    }


@router.post("/logout")
def logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie("session_token")
    return {"message": "Logged out"}


# ─── Agent Claim Flow ──────────────────────────────

class ClaimRequest(BaseModel):
    email: str


@router.post("/claim/{claim_token}")
def initiate_claim(
    claim_token: str,
    req: ClaimRequest,
    db: Session = Depends(get_db),
):
    """
    Step 1 of claim: human provides email.
    Sends a magic link that will complete the claim.
    """
    claim = db.query(AgentClaimRecord).filter(
        AgentClaimRecord.claim_token == claim_token,
        AgentClaimRecord.status == "pending",
    ).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim link not found or already used")

    # Ensure user exists
    user = db.query(UserRecord).filter(UserRecord.email == req.email).first()
    if not user:
        user = UserRecord(id=str(uuid.uuid4()), email=req.email)
        db.add(user)
        db.commit()

    # Create magic link with claim context
    token = create_magic_link(
        req.email,
        "claim",
        db,
        metadata={"claim_token": claim_token},
        expiry_minutes=15,
    )
    send_magic_link(req.email, token, "claim")

    agent = db.query(AgentRecord).filter(AgentRecord.did == claim.agent_did).first()
    return {
        "message": "Claim link sent to your email!",
        "agent_name": agent.name if agent else None,
        "agent_did": claim.agent_did,
    }


@router.get("/claim/complete")
def complete_claim(
    token: str = Query(...),
    response: Response = None,
    db: Session = Depends(get_db),
):
    """
    Step 2 of claim: consume magic link → link agent to human account.
    """
    record = resolve_magic_link(token, db)
    if not record or record.purpose != "claim":
        raise HTTPException(status_code=400, detail="Invalid or expired claim link")

    metadata = json.loads(record.metadata_json or "{}")
    claim_token = metadata.get("claim_token")
    if not claim_token:
        raise HTTPException(status_code=400, detail="Claim context missing")

    claim = db.query(AgentClaimRecord).filter(
        AgentClaimRecord.claim_token == claim_token,
        AgentClaimRecord.status == "pending",
    ).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim already completed")

    # Get or create user
    user = db.query(UserRecord).filter(UserRecord.email == record.email).first()
    if not user:
        user = UserRecord(id=str(uuid.uuid4()), email=record.email)
        db.add(user)

    user.email_verified = True
    user.last_login_at = datetime.now(timezone.utc)

    # Complete claim
    claim.user_id = user.id
    claim.claimed_at = datetime.now(timezone.utc)
    claim.status = "claimed"

    # Update agent
    agent = db.query(AgentRecord).filter(AgentRecord.did == claim.agent_did).first()
    if agent:
        agent.owner_id = user.id
        agent.is_claimed = True

    db.commit()
    db.refresh(user)

    jwt_token = create_jwt(user.id, user.email, user.role)
    response.set_cookie(
        key="session_token", value=jwt_token,
        httponly=True, samesite="lax",
        secure=settings.is_production, max_age=60 * 60 * 24 * 7,
    )

    return {
        "message": f"Agent '{agent.name if agent else claim.agent_did}' claimed successfully!",
        "agent_did": claim.agent_did,
        "session_token": jwt_token,
        "user": {"id": user.id, "email": user.email},
    }
