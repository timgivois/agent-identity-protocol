"""
DID Document resolution endpoints.
W3C-compatible DID resolution for the did:agent method.
"""
import base64
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, AgentRecord
from ..core.did import build_did_document, did_to_public_bytes
from ..core.crypto import b64_to_public_bytes

router = APIRouter(tags=["identity"])


@router.get("/.well-known/did/{did:path}")
def resolve_did(did: str, db: Session = Depends(get_db)):
    """
    Resolve a DID to its W3C DID Document.
    This is the public-facing identity proof for an agent.
    """
    agent = db.query(AgentRecord).filter(AgentRecord.did == did).first()
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"DID not found: {did}",
            headers={"Content-Type": "application/did+ld+json"}
        )

    public_bytes = b64_to_public_bytes(agent.public_key_b64)
    doc = build_did_document(did, public_bytes, agent.name)
    return doc
