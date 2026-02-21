"""
DID generation and resolution for the did:agent method.

DID format: did:agent:<base58-encoded-public-key>

W3C DID spec compliant structure.
"""
import base58


def public_key_to_did(public_bytes: bytes) -> str:
    """Generate a DID from a public key."""
    encoded = base58.b58encode(public_bytes).decode()
    return f"did:agent:{encoded}"


def did_to_public_bytes(did: str) -> bytes:
    """Extract public key bytes from a DID."""
    if not did.startswith("did:agent:"):
        raise ValueError(f"Invalid DID method: {did}")
    encoded = did.removeprefix("did:agent:")
    return base58.b58decode(encoded)


def build_did_document(did: str, public_bytes: bytes, agent_name: str) -> dict:
    """
    Build a W3C-compatible DID Document.
    https://www.w3.org/TR/did-core/
    """
    import base64
    public_b64 = base64.urlsafe_b64encode(public_bytes).decode().rstrip("=")

    return {
        "@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1"
        ],
        "id": did,
        "controller": did,
        "verificationMethod": [
            {
                "id": f"{did}#key-1",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyMultibase": f"z{base58.b58encode(public_bytes).decode()}"
            }
        ],
        "authentication": [f"{did}#key-1"],
        "assertionMethod": [f"{did}#key-1"],
        "service": [
            {
                "id": f"{did}#agent",
                "type": "AgentIdentityService",
                "serviceEndpoint": f"/agents/{did}",
                "description": f"AI Agent: {agent_name}"
            }
        ]
    }
