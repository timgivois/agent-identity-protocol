"""
Authentication system.

Agents   → Bearer API key (ak_xxxx...)
Humans   → Magic link email → JWT session cookie
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Header, Cookie, Request
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from .db import get_db, ApiKeyRecord, AgentRecord, UserRecord, MagicLinkRecord
from .config import settings

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 7 days
MAGIC_LINK_EXPIRY_MINUTES = 15


# ─── API Key utilities ─────────────────────────────

def generate_api_key() -> tuple[str, str]:
    """
    Generate a new API key.
    Returns (raw_key, key_hash).
    raw_key is shown to the agent ONCE. key_hash is stored.
    Format: ak_<random_hex_48>
    """
    raw = f"{settings.api_key_prefix}_{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_hash


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_api_key_record(agent_did: str, db: Session) -> tuple[str, ApiKeyRecord]:
    """Create and store a new API key for an agent. Returns (raw_key, record)."""
    raw_key, key_hash = generate_api_key()
    record = ApiKeyRecord(
        id=str(uuid.uuid4()),
        key_hash=key_hash,
        key_prefix=raw_key[:10],
        agent_did=agent_did,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return raw_key, record


def resolve_api_key(raw_key: str, db: Session) -> Optional[ApiKeyRecord]:
    """Lookup an API key by its raw value. Updates last_used_at."""
    key_hash = hash_key(raw_key)
    record = db.query(ApiKeyRecord).filter(
        ApiKeyRecord.key_hash == key_hash,
        ApiKeyRecord.revoked == False,
    ).first()
    if record:
        record.last_used_at = datetime.now(timezone.utc)
        db.commit()
    return record


# ─── JWT utilities ─────────────────────────────────

def create_jwt(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": datetime.now(timezone.utc).timestamp(),
        "exp": (datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


# ─── Magic link utilities ──────────────────────────

def create_magic_link(
    email: str,
    purpose: str,
    db: Session,
    metadata: dict = None,
    expiry_minutes: int = MAGIC_LINK_EXPIRY_MINUTES,
) -> str:
    """Create a magic link token. Returns the raw token."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    import json
    record = MagicLinkRecord(
        id=str(uuid.uuid4()),
        token_hash=token_hash,
        email=email,
        purpose=purpose,
        metadata_json=json.dumps(metadata or {}),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes),
    )
    db.add(record)
    db.commit()
    return raw_token


def resolve_magic_link(raw_token: str, db: Session) -> Optional[MagicLinkRecord]:
    """Validate and consume a magic link token. Returns record if valid."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    record = db.query(MagicLinkRecord).filter(
        MagicLinkRecord.token_hash == token_hash,
        MagicLinkRecord.used_at == None,
    ).first()
    if not record:
        return None
    if datetime.now(timezone.utc) > record.expires_at.replace(tzinfo=timezone.utc):
        return None
    # Mark as used
    record.used_at = datetime.now(timezone.utc)
    db.commit()
    return record


# ─── FastAPI dependency: current agent ────────────

async def get_current_agent(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> AgentRecord:
    """Require a valid agent API key. Use as FastAPI dependency."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key. Use: Authorization: Bearer ak_xxx")
    raw_key = authorization.removeprefix("Bearer ").strip()
    key_record = resolve_api_key(raw_key, db)
    if not key_record:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    agent = db.query(AgentRecord).filter(AgentRecord.did == key_record.agent_did).first()
    if not agent or not agent.is_active:
        raise HTTPException(status_code=401, detail="Agent not found or inactive")
    return agent


async def get_current_agent_optional(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[AgentRecord]:
    """Like get_current_agent but doesn't raise if missing."""
    if not authorization:
        return None
    try:
        return await get_current_agent(authorization, db)
    except HTTPException:
        return None


# ─── FastAPI dependency: current human user ────────

async def get_current_user(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> UserRecord:
    """Require a valid human session (JWT in Authorization header or cookie)."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization.removeprefix("Bearer ").strip()
        # Only treat as JWT if it's not an api key
        if not raw.startswith(settings.api_key_prefix + "_"):
            token = raw
    if not token and session_token:
        token = session_token
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = db.query(UserRecord).filter(UserRecord.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> Optional[UserRecord]:
    try:
        return await get_current_user(authorization, session_token, db)
    except HTTPException:
        return None
