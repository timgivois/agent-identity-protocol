# Build Task: AI Agent Identity Protocol MVP

## Tech Stack
Python + FastAPI + SQLite + Ed25519 cryptography

## Project Structure to Create
```
app/
  main.py          - FastAPI entrypoint
  models.py        - Pydantic models
  db.py            - SQLite via SQLAlchemy
  routes/
    agents.py      - Agent CRUD endpoints
    identity.py    - DID + keypair management
    handshake.py   - Agent-to-agent auth
  core/
    crypto.py      - Keypair gen, sign, verify (Ed25519)
    did.py         - DID generation (did:agent method)
tests/
  test_handshake.py
requirements.txt
.env.example
README.md
```

## Core Features

### 1. Agent Registration
- POST /agents/register — takes name + owner_id, generates Ed25519 keypair, returns DID
- GET /agents/{did} — get agent info
- GET /agents/ — list all agents

### 2. DID Format
- Format: did:agent:<base58-encoded-public-key>
- GET /.well-known/did/{did} — returns W3C-compatible DID Document

### 3. Handshake Protocol (core feature)
- POST /handshake/challenge — Agent A requests a challenge nonce targeting Agent B's DID
- POST /handshake/verify — Agent A signs the nonce with its private key; server verifies using Agent A's public key; returns JWT session token if valid

### 4. Crypto
- Ed25519 keypairs via the `cryptography` library
- Private key stored encrypted (Fernet symmetric encryption, master secret from env)
- base58 encoding for DIDs

## Dependencies (requirements.txt)
- fastapi
- uvicorn[standard]
- sqlalchemy
- cryptography
- base58
- python-jose[cryptography]
- pydantic-settings
- python-dotenv

## .env.example
```
MASTER_SECRET=change-me-to-a-random-32-char-string
JWT_SECRET=another-random-secret
DATABASE_URL=sqlite:///./agent_identity.db
```

## README
Write a clear README with:
- What this is: identity layer for AI agents
- Why it matters: verified agent-to-agent trust
- How to run locally (pip install, uvicorn)
- Handshake flow explained with curl examples
- Future roadmap: blockchain anchoring, hardware key, human review marketplace

## Tests
At least one test in tests/test_handshake.py that:
1. Registers two agents
2. Requests a challenge from agent A targeting agent B
3. Signs the challenge with agent A's private key
4. Verifies the signature and gets a session token
5. Asserts the token is valid

## Important
- Keep it simple and actually working
- SQLite so zero infra needed
- This is an MVP, not production code
- Make it run with: pip install -r requirements.txt && uvicorn app.main:app --reload

When completely finished, run:
openclaw system event --text "Done: Agent Identity Protocol MVP built — FastAPI + Ed25519 + DID handshake ready" --mode now
