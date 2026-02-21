"""
Agent registration and management endpoints.
"""
import base64
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, AgentRecord
from ..models import AgentRegisterRequest, AgentResponse, AgentListResponse
from ..core.crypto import generate_keypair, encrypt_private_key, public_bytes_to_b64
from ..core.did import public_key_to_did
from ..config import settings

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/register", response_model=AgentResponse, status_code=201)
def register_agent(request: AgentRegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new AI agent.
    Generates an Ed25519 keypair and a DID (did:agent:<base58-public-key>).
    """
    # Generate keypair
    private_bytes, public_bytes = generate_keypair()

    # Create DID
    did = public_key_to_did(public_bytes)

    # Check for collision (extremely unlikely with Ed25519, but be safe)
    existing = db.query(AgentRecord).filter(AgentRecord.did == did).first()
    if existing:
        raise HTTPException(status_code=409, detail="DID collision — try again")

    # Encrypt private key before storage
    encrypted_private = encrypt_private_key(private_bytes, settings.master_secret)
    public_b64 = public_bytes_to_b64(public_bytes)

    # Store agent
    agent = AgentRecord(
        did=did,
        name=request.name,
        owner_id=request.owner_id,
        public_key_b64=public_b64,
        encrypted_private_key=encrypted_private,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    return agent


@router.get("/", response_model=AgentListResponse)
def list_agents(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """List all registered agents."""
    agents = db.query(AgentRecord).offset(skip).limit(limit).all()
    total = db.query(AgentRecord).count()
    return AgentListResponse(agents=agents, total=total)


@router.get("/{did:path}", response_model=AgentResponse)
def get_agent(did: str, db: Session = Depends(get_db)):
    """Get agent info by DID."""
    agent = db.query(AgentRecord).filter(AgentRecord.did == did).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {did}")
    return agent
