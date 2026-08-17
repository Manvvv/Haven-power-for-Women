"""
Haven Authentication, Authorization & Cryptography Module.
Provides:
- JWT token creation and verification (Clerk session & Haven internal tokens)
- Role-based authorization dependencies (User, Authority, Admin)
- PBKDF2-HMAC-SHA256 salted safe-word & password hashing
- AES-256-GCM symmetric evidence encryption & decryption at rest
"""

import os
import re
import time
import base64
import hashlib
import hmac
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

import jwt
from fastapi import Header, HTTPException, status, Depends
from pydantic import BaseModel
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ─── Configuration & Secrets ──────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET", "haven_jwt_secret_key_change_in_production_2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Authority portal master key / password (default to haven2024 if not configured, but checked server-side)
AUTHORITY_SECRET_KEY = os.getenv("AUTHORITY_SECRET_KEY", "haven2024")

# Evidence 256-bit encryption key (AES-GCM)
# Derive a 32-byte key from EVIDENCE_ENCRYPTION_KEY env var or fallback
_RAW_EVID_KEY = os.getenv("EVIDENCE_ENCRYPTION_KEY", "haven_evidence_master_encryption_key_32bytes_sec")
EVIDENCE_AES_KEY = hashlib.sha256(_RAW_EVID_KEY.encode("utf-8")).digest()


# ─── Data Models ──────────────────────────────────────────

class AuthUser(BaseModel):
    user_id: str
    role: str = "user"  # "user", "authority", "admin"
    email: Optional[str] = None
    name: Optional[str] = None
    is_authenticated: bool = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    expires_in: int


class AuthorityLoginModel(BaseModel):
    password: str
    badge_number: Optional[str] = "PO-1091"
    station: Optional[str] = "Central Station"
    officer_name: Optional[str] = "Duty Officer"


# ─── JWT & Token Utilities ────────────────────────────────

def create_access_token(
    user_id: str,
    role: str = "user",
    email: Optional[str] = None,
    name: Optional[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=JWT_EXPIRATION_HOURS))
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "role": role,
        "email": email,
        "name": name,
        "exp": expire,
        "iat": datetime.utcnow(),
        "iss": "haven-backend",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT token.
    Supports Haven internal HS256 tokens as well as Clerk JWT tokens.
    """
    try:
        # First attempt decoding as internal Haven JWT
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], issuer="haven-backend")
    except jwt.InvalidIssuerError:
        # Might be a Clerk JWT token or external token - decode without verifying issuer with secret,
        # or decode unverified header/claims if Clerk public key is not configured locally
        try:
            # Decode payload (for Clerk tokens in development/production)
            unverified_payload = jwt.decode(token, options={"verify_signature": False})
            user_id = unverified_payload.get("sub") or unverified_payload.get("user_id") or "user"
            return {
                "sub": user_id,
                "user_id": user_id,
                "role": unverified_payload.get("role", "user"),
                "email": unverified_payload.get("email"),
                "name": unverified_payload.get("name"),
                "exp": unverified_payload.get("exp"),
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token claims: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── FastAPI Dependencies ─────────────────────────────────

def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[AuthUser]:
    """Extract and validate user from Authorization header if present."""
    if not authorization:
        return None
    try:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        payload = decode_token(token)
        return AuthUser(
            user_id=payload.get("user_id") or payload.get("sub", "anon"),
            role=payload.get("role", "user"),
            email=payload.get("email"),
            name=payload.get("name"),
            is_authenticated=True,
        )
    except Exception:
        return None


def get_current_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """FastAPI dependency requiring a valid Bearer token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Expected 'Authorization: Bearer <token>' header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    return AuthUser(
        user_id=payload.get("user_id") or payload.get("sub", "anon"),
        role=payload.get("role", "user"),
        email=payload.get("email"),
        name=payload.get("name"),
        is_authenticated=True,
    )


def require_authority(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """FastAPI dependency requiring authority or admin role."""
    if current_user.role not in ["authority", "admin", "police", "protection_officer"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Authority credentials required for this action.",
        )
    return current_user


def require_admin(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """FastAPI dependency requiring admin role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Administrator credentials required.",
        )
    return current_user


def verify_authority_password(plain_password: str) -> bool:
    """Constant-time comparison for authority password."""
    return hmac.compare_digest(plain_password.strip(), AUTHORITY_SECRET_KEY.strip())


# ─── Salted Safe-Word & Password Hashing (PBKDF2) ─────────

def normalize_text(text: str) -> str:
    """Normalize text for voice matching."""
    normalized = re.sub(r'[^\w\s]', '', text.lower()).strip()
    return ' '.join(normalized.split())


def hash_safe_word_salted(word: str, salt: Optional[str] = None) -> Dict[str, str]:
    """
    Hash a safe word using PBKDF2-HMAC-SHA256 with 100,000 iterations and random salt.
    Returns dict with 'hash' and 'salt' in hex format.
    """
    norm = normalize_text(word)
    if not salt:
        salt_bytes = secrets.token_bytes(16)
        salt_hex = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt)
        salt_hex = salt

    key = hashlib.pbkdf2_hmac(
        'sha256',
        norm.encode('utf-8'),
        salt_bytes,
        100000,
        dklen=32
    )
    return {
        "hash": key.hex(),
        "salt": salt_hex,
    }


def verify_safe_word(spoken_phrase: str, stored_hash: str, salt_hex: str) -> bool:
    """Verify spoken phrase against stored salted hash in constant time."""
    norm = normalize_text(spoken_phrase)
    try:
        salt_bytes = bytes.fromhex(salt_hex)
    except Exception:
        return False
    calculated = hashlib.pbkdf2_hmac(
        'sha256',
        norm.encode('utf-8'),
        salt_bytes,
        100000,
        dklen=32
    ).hex()
    return hmac.compare_digest(calculated, stored_hash)


# ─── AES-256-GCM Evidence Encryption ─────────────────────

def encrypt_evidence_payload(data: str) -> Dict[str, str]:
    """
    Encrypt sensitive evidence data (base64 string or text) using AES-256-GCM.
    Returns encrypted ciphertext and nonce in base64.
    """
    if not data:
        return {"ciphertext": "", "nonce": ""}
    aesgcm = AESGCM(EVIDENCE_AES_KEY)
    nonce = secrets.token_bytes(12)  # 96-bit nonce for GCM
    encrypted_bytes = aesgcm.encrypt(nonce, data.encode("utf-8"), None)
    return {
        "ciphertext": base64.b64encode(encrypted_bytes).decode("utf-8"),
        "nonce": base64.b64encode(nonce).decode("utf-8"),
    }


def decrypt_evidence_payload(ciphertext_b64: str, nonce_b64: str) -> str:
    """
    Decrypt AES-256-GCM encrypted evidence payload.
    """
    if not ciphertext_b64 or not nonce_b64:
        return ""
    try:
        aesgcm = AESGCM(EVIDENCE_AES_KEY)
        ciphertext = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        return f"[Decryption error: {str(e)}]"
