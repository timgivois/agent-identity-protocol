"""
Agent Identity Protocol — FastAPI entrypoint.

v0.1  Identity layer  — DID + Ed25519 keypairs + handshake protocol
v0.4  Orchestration   — Roles, Workflows, Heuristic validators, Human gates
v1.0  Marketplace     — Reviewers (DID-verified), Task queue, Reputation, Commission
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import create_tables
from .routes import agents, identity, handshake, roles, workflows, gates, marketplace


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title="Agent Identity Protocol",
    description="""
## Identity + Orchestration + Marketplace for AI Agents

### v0.1 — Identity
Every AI agent gets a **DID** (`did:agent:<base58-public-key>`) backed by Ed25519.
Agents prove identity via cryptographic challenge-response handshake.

### v0.4 — Orchestration
- **Roles** — define what an agent does (input/output schema, webhook, heuristics)
- **Workflows** — chain roles into sequential pipelines
- **Heuristic validators** — auto-check output (word count, keywords, sentiment)
- **Human gates** — pause workflow for review when heuristics pass but stakes are high

### v1.0 — Marketplace
- **Reviewers** — humans with verified DIDs who review agent output
- **Task queue** — claim and complete review tasks for commission
- **Reputation** — on-chain-ready score built from task history
- **Progressive automation** — gates learn from human decisions over time

---

### Core Flow
```
Brief → Role(Agent) → [Heuristic OK?]
  NO  → retry
  YES → [Gate required?]
          NO  → next node
          YES → Marketplace task → Reviewer claims → Decision
                  approved → next node
                  rejected → requester retries
```
""",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# v0.1 — Identity
app.include_router(agents.router)
app.include_router(identity.router)
app.include_router(handshake.router)

# v0.4 — Orchestration
app.include_router(roles.router)
app.include_router(workflows.router)
app.include_router(gates.router)

# v1.0 — Marketplace
app.include_router(marketplace.router)


@app.get("/", tags=["root"])
def root():
    return {
        "name": "Agent Identity Protocol",
        "version": "1.0.0",
        "layers": {
            "identity":      "/agents, /handshake, /.well-known/did",
            "orchestration": "/roles, /workflows, /gates",
            "marketplace":   "/marketplace/reviewers, /marketplace/tasks",
        },
        "docs": "/docs",
    }


@app.get("/health", tags=["root"])
def health():
    return {"status": "ok"}
