"""
Agent Marketplace — Production API

v0.1  Identity      — DID + Ed25519 + handshake
v0.4  Orchestration — Roles, Workflows, Heuristics, Human gates
v1.0  Marketplace   — Reviewers, Tasks, Reputation, Commission
prod  Platform      — Auth (API keys + magic links), Rate limiting, PostgreSQL
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .db import create_tables
from .config import settings
from .routes import agents, identity, handshake, roles, workflows, gates, marketplace, auth

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title="Agent Marketplace",
    description="""
## The marketplace for human review of AI agent output.

### How it works
1. **Agents** register and get an API key → build workflows with human review gates
2. **Humans** sign up as reviewers → claim tasks → earn commission
3. **Quality guaranteed** — heuristics filter bad output before humans see it
4. **Identity verified** — every agent has a cryptographic DID

### Auth
- **Agents:** `Authorization: Bearer ak_xxx`
- **Humans:** Magic link email → JWT session cookie
""",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──────────────────────────────────────────
# Auth (production)
app.include_router(auth.router)

# Identity (v0.1)
app.include_router(agents.router)
app.include_router(identity.router)
app.include_router(handshake.router)

# Orchestration (v0.4)
app.include_router(roles.router)
app.include_router(workflows.router)
app.include_router(gates.router)

# Marketplace (v1.0)
app.include_router(marketplace.router)


@app.get("/", tags=["root"])
def root():
    return {
        "name": "Agent Marketplace",
        "version": "1.0.0",
        "environment": settings.environment,
        "endpoints": {
            "auth":          "/auth — agent registration, human login, claim flow",
            "identity":      "/agents, /handshake, /.well-known/did",
            "orchestration": "/roles, /workflows, /gates",
            "marketplace":   "/marketplace/reviewers, /marketplace/tasks",
        },
        "docs": "/docs",
    }


@app.get("/health", tags=["root"])
def health():
    return {"status": "ok", "environment": settings.environment}
