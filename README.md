# Agent Identity Protocol

> Identity layer for AI agents — cryptographic proof of who an agent is.

## What is this?

AI agents are proliferating fast, but there's no standard way for one agent to *prove its identity* to another. This protocol fixes that.

Every agent gets a **Decentralized Identifier (DID)** backed by an **Ed25519 keypair**. Agents can challenge each other to prove they control their DID via a signature — no centralized trust required.

```
did:agent:7EcVx3GhPqnKWmBsXzqY...
```

## Why it matters

Without identity, agents are anonymous. Any system claiming to be "agent B" could be a rogue agent. With this protocol:

- **Agents can authenticate to each other** — not just to humans
- **Identity is portable** — your DID moves with you across platforms
- **No passwords** — pure cryptography, Ed25519 signatures
- **Foundation for trust networks** — build authorization on top of verified identity

## Quick Start

```bash
git clone https://github.com/timgivois/agent-identity-protocol
cd agent-identity-protocol

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your secrets

# Run
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for the interactive API explorer.

## Handshake Flow

```
Agent A                    Server                    Agent B
   |                          |                          |
   |-- POST /handshake/challenge (requester=A, target=B) |
   |                          |                          |
   |<-- nonce: "a3f9b2..."    |                          |
   |                          |                          |
   | sign(nonce, private_key_A)                          |
   |                          |                          |
   |-- POST /handshake/verify (nonce, did_A, signature) -|
   |                          |                          |
   |        verify(signature, public_key_A)              |
   |                          |                          |
   |<-- JWT session token ✅   |                          |
```

## API Example (curl)

### 1. Register an agent

```bash
curl -X POST http://localhost:8000/agents/register \
  -H "Content-Type: application/json" \
  -d '{"name": "copywriter-agent-01", "owner_id": "user_tim_001"}'
```

```json
{
  "did": "did:agent:7EcVx3GhPqnKWmBsXzqY...",
  "name": "copywriter-agent-01",
  "owner_id": "user_tim_001",
  "public_key_b64": "abc123...",
  "created_at": "2026-02-20T19:00:00Z"
}
```

### 2. Request a challenge

```bash
curl -X POST http://localhost:8000/handshake/challenge \
  -H "Content-Type: application/json" \
  -d '{
    "requester_did": "did:agent:AAA...",
    "target_did": "did:agent:BBB..."
  }'
```

```json
{
  "nonce": "a3f9b2c1d4e5f6...",
  "requester_did": "did:agent:AAA...",
  "target_did": "did:agent:BBB...",
  "expires_in_seconds": 300
}
```

### 3. Sign & verify (Python)

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import base64, requests

# Sign the nonce with your private key
nonce = "a3f9b2c1d4e5f6..."
signature = private_key.sign(nonce.encode())
signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")

# Verify
response = requests.post("http://localhost:8000/handshake/verify", json={
    "nonce": nonce,
    "requester_did": "did:agent:AAA...",
    "signature_b64": signature_b64,
})
# response.json()["session_token"] → your JWT
```

### 4. Resolve a DID Document

```bash
curl http://localhost:8000/.well-known/did/did:agent:AAA...
```

```json
{
  "@context": ["https://www.w3.org/ns/did/v1", "..."],
  "id": "did:agent:AAA...",
  "verificationMethod": [{
    "type": "Ed25519VerificationKey2020",
    "publicKeyMultibase": "z7EcVx3..."
  }]
}
```

## Run Tests

```bash
pytest tests/ -v
```

## Roadmap

### v0.2 — Blockchain Anchoring
- Register DID on-chain (Polygon ID / Privado ID)
- Hash of SOUL.md + IDENTITY.md anchored as metadata
- `did:agent` as a W3C DID method

### v0.3 — Hardware Key
- Private key lives on a physical USB device (like Ledger, but for agents)
- Signing happens locally — key never leaves the device
- Ownership proof: hardware key + DID = your agent fleet

### v0.4 — Agent Orchestration
- Define roles: copywriter, designer, PM, QA
- Chain roles into workflows
- Human review gates with quality heuristics
- Reviewer marketplace (gig economy for AI oversight)

### v1.0 — Marketplace
- Human reviewers have DIDs + reputation on-chain
- Earn by reviewing agent outputs at quality gates
- Progressive automation: human gates → AI heuristics over time

---

## Tech Stack

| Layer | Tech |
|-------|------|
| API | FastAPI + Uvicorn |
| Crypto | Ed25519 (via `cryptography` library) |
| DID | `did:agent` method (custom, W3C DID Core compatible) |
| Storage | SQLite via SQLAlchemy |
| Tokens | JWT (python-jose) |
| Key storage | Fernet symmetric encryption |

---

*"Contrata tu equipo de agentes una vez, trabajan para siempre."*
