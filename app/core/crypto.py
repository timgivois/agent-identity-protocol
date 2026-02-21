"""
Cryptographic primitives for agent identity.
Ed25519 keypairs, signing, and verification.
"""
import os
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)
from cryptography.fernet import Fernet
import hashlib


def get_fernet_key(master_secret: str) -> bytes:
    """Derive a Fernet-compatible key from the master secret."""
    digest = hashlib.sha256(master_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def generate_keypair() -> tuple[bytes, bytes]:
    """
    Generate an Ed25519 keypair.
    Returns (private_key_bytes, public_key_bytes) — raw bytes.
    """
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption()
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw
    )
    return private_bytes, public_bytes


def encrypt_private_key(private_bytes: bytes, master_secret: str) -> str:
    """Encrypt private key bytes using Fernet (symmetric). Returns base64 string."""
    fernet = Fernet(get_fernet_key(master_secret))
    encrypted = fernet.encrypt(private_bytes)
    return encrypted.decode()


def decrypt_private_key(encrypted: str, master_secret: str) -> bytes:
    """Decrypt private key. Returns raw bytes."""
    fernet = Fernet(get_fernet_key(master_secret))
    return fernet.decrypt(encrypted.encode())


def sign_message(private_bytes: bytes, message: bytes) -> bytes:
    """Sign a message with Ed25519 private key. Returns signature bytes."""
    private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    return private_key.sign(message)


def verify_signature(public_bytes: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature. Returns True if valid."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature

    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        public_key.verify(signature, message)
        return True
    except InvalidSignature:
        return False


def public_bytes_to_b64(public_bytes: bytes) -> str:
    """Encode public key bytes to base64 URL-safe string."""
    return base64.urlsafe_b64encode(public_bytes).decode().rstrip("=")


def b64_to_public_bytes(b64_str: str) -> bytes:
    """Decode base64 URL-safe string to public key bytes."""
    padding = 4 - len(b64_str) % 4
    if padding != 4:
        b64_str += "=" * padding
    return base64.urlsafe_b64decode(b64_str)
