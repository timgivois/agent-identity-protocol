"""
Role management — define what an agent does.
"""
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ..db import get_db, RoleRecord

router = APIRouter(prefix="/roles", tags=["orchestration"])


class RoleCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    owner_id: str
    webhook_url: Optional[str] = None
    input_schema: Optional[dict] = {}
    output_schema: Optional[dict] = {}
    heuristic_config: Optional[dict] = {}


class RoleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    owner_id: str
    webhook_url: Optional[str]
    input_schema: dict
    output_schema: dict
    heuristic_config: dict
    created_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_record(cls, r: RoleRecord) -> "RoleResponse":
        return cls(
            id=r.id,
            name=r.name,
            description=r.description,
            owner_id=r.owner_id,
            webhook_url=r.webhook_url,
            input_schema=json.loads(r.input_schema or "{}"),
            output_schema=json.loads(r.output_schema or "{}"),
            heuristic_config=json.loads(r.heuristic_config or "{}"),
            created_at=r.created_at,
        )


@router.post("/", response_model=RoleResponse, status_code=201)
def create_role(req: RoleCreateRequest, db: Session = Depends(get_db)):
    """
    Create a role. Roles define what an agent does.

    heuristic_config supports:
    - min_words / max_words
    - min_chars / max_chars
    - required_keywords: ["brand", "CTA"]
    - forbidden_keywords: ["competitor"]
    - must_contain_url: true
    - required_sentiment: "positive"
    """
    role = RoleRecord(
        id=str(uuid.uuid4()),
        name=req.name,
        description=req.description,
        owner_id=req.owner_id,
        webhook_url=req.webhook_url,
        input_schema=json.dumps(req.input_schema or {}),
        output_schema=json.dumps(req.output_schema or {}),
        heuristic_config=json.dumps(req.heuristic_config or {}),
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return RoleResponse.from_record(role)


@router.get("/", response_model=list[RoleResponse])
def list_roles(owner_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(RoleRecord)
    if owner_id:
        q = q.filter(RoleRecord.owner_id == owner_id)
    return [RoleResponse.from_record(r) for r in q.all()]


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(role_id: str, db: Session = Depends(get_db)):
    role = db.query(RoleRecord).filter(RoleRecord.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return RoleResponse.from_record(role)


@router.delete("/{role_id}", status_code=204)
def delete_role(role_id: str, db: Session = Depends(get_db)):
    role = db.query(RoleRecord).filter(RoleRecord.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    db.delete(role)
    db.commit()
