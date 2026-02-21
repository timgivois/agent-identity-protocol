"""
Agent Identity Protocol — FastAPI entrypoint.

An identity layer for AI agents:
- Every agent has a verifiable DID (Decentralized Identifier)
- Cryptographic proof of identity via Ed25519 signatures
- Agent-to-agent handshake protocol
- W3C DID Document resolution
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import create_tables
from .routes import agents, identity, handshake

app = FastAPI(
    title="Agent Identity Protocol",
    description="""
## Identity layer for AI agents

Every AI agent gets a **Decentralized Identifier (DID)** backed by an Ed25519 keypair.
Agents can cryptographically prove who they are via a challenge-response handshake.

### Core Concepts
- **DID format:** `did:agent:<base58-encoded-public-key>`
- **Keypair:** Ed25519 — fast, secure, small signatures
- **Handshake:** challenge → sign → verify → JWT session token
- **DID Document:** W3C-compatible public identity document

### Handshake Flow
1. `POST /handshake/challenge` — get a nonce to sign
2. Sign the nonce with your private key (Ed25519)
3. `POST /handshake/verify` — submit signature, receive session token
""",
    version="0.1.0",
    contact={
        "name": "Agent Identity Protocol",
        "url": "https://github.com/timgivois/agent-identity-protocol",
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(agents.router)
app.include_router(identity.router)
app.include_router(handshake.router)


@app.on_event("startup")
def on_startup():
    create_tables()


@app.get("/", tags=["root"])
def root():
    return {
        "name": "Agent Identity Protocol",
        "version": "0.1.0",
        "description": "Identity layer for AI agents — DID + Ed25519 + handshake protocol",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health", tags=["root"])
def health():
    return {"status": "ok"}
