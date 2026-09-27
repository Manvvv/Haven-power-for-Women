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
import logging
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

import jwt
from fastapi import Header, HTTPException, status, Depends
from pydantic import BaseModel
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ─── Configuration & Secrets ──────────────────────────────

# Insecure development-only fallbacks. Production MUST override these (enforced
# by _validate_production_config() below — the app refuses to boot otherwise).
_DEFAULT_JWT_SECRET = "haven_jwt_secret_key_change_in_production_2026"
_DEFAULT_AUTHORITY_KEY = "haven2024"
_DEFAULT_EVIDENCE_KEY = "haven_evidence_master_encryption_key_32bytes_sec"

# JWT signing secrets that must NEVER reach production. This includes the dev
# fallback above AND the placeholder shipped in backend/.env.example: an operator
# who copies that template verbatim would otherwise run a repo-visible (public)
# signing secret, letting anyone forge Haven-issued tokens. The production guard
# below rejects every value in this set. (AUTHORITY_SECRET_KEY and
# EVIDENCE_ENCRYPTION_KEY need no equivalent list — their .env.example
# placeholders are identical to the defaults above and are already caught.)
_INSECURE_JWT_SECRETS = frozenset({
    _DEFAULT_JWT_SECRET,
    "haven_production_jwt_secret_please_change_me_32chars",
})

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT in ("production", "prod")

logger = logging.getLogger("haven_backend")

# Single stable, client-facing authentication error. Internal exception text,
# issuer/key details, JWKS URLs and signing configuration are NEVER placed in a
# client response — they are only logged internally by reason CATEGORY.
_GENERIC_AUTH_ERROR = "Invalid or expired authentication token"


def _auth_error(reason: str) -> HTTPException:
    """Build a sanitized 401 and log only a coarse reason category (no token/secrets)."""
    logger.info("Auth failure (reason=%s)", reason)
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_GENERIC_AUTH_ERROR,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes")


JWT_SECRET = os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# ─── Clerk (external identity provider) verification ──────
# Clerk issues RS256 session JWTs. We verify them against Clerk's public JWKS.
# Configure CLERK_ISSUER (e.g. https://your-app.clerk.accounts.dev) or CLERK_JWKS_URL.
CLERK_ISSUER = (os.getenv("CLERK_ISSUER") or "").strip().rstrip("/")
CLERK_JWKS_URL = (os.getenv("CLERK_JWKS_URL") or "").strip() or (
    f"{CLERK_ISSUER}/.well-known/jwks.json" if CLERK_ISSUER else ""
)
# When true, tokens that cannot be cryptographically verified are REJECTED outright.
# Defaults to TRUE in production (fail closed) and FALSE in local development.
# An unverifiable external token can NEVER grant an elevated (authority/admin) role
# regardless of this flag — role is forced to "user".
STRICT_AUTH = _env_bool("STRICT_AUTH", IS_PRODUCTION)

# Lazy, cached JWKS client (PyJWT ships PyJWKClient; it fetches + caches Clerk keys).
_jwks_client = None


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None and CLERK_JWKS_URL:
        try:
            from jwt import PyJWKClient
            _jwks_client = PyJWKClient(CLERK_JWKS_URL, cache_keys=True)
        except Exception as e:  # pragma: no cover - network/config dependent
            logging.getLogger("haven_backend").warning(f"Could not init Clerk JWKS client: {e}")
            _jwks_client = None
    return _jwks_client


def _extract_role(claims: Dict[str, Any]) -> str:
    """Pull a role from Clerk claims, checking common metadata locations."""
    role = claims.get("role")
    if not role:
        for container in ("public_metadata", "publicMetadata", "metadata"):
            meta = claims.get(container)
            if isinstance(meta, dict) and meta.get("role"):
                role = meta.get("role")
                break
    return (role or "user").lower()


def _verify_clerk_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a Clerk-issued RS256 JWT against Clerk's JWKS.
    Returns the verified claims dict, or None if verification is not possible.
    Raises HTTPException only for tokens that are present but definitively invalid.
    """
    client = _get_jwks_client()
    if client is None:
        return None  # JWKS not configured — caller decides how to degrade
    signing_key = client.get_signing_key_from_jwt(token)
    decode_kwargs: Dict[str, Any] = {
        "algorithms": ["RS256"],
        # Clerk audience varies by template; we don't enforce it here.
        "options": {"verify_aud": False},
    }
    if CLERK_ISSUER:
        decode_kwargs["issuer"] = CLERK_ISSUER
    return jwt.decode(token, signing_key.key, **decode_kwargs)

# Authority portal master key / password (dev fallback; production must override)
AUTHORITY_SECRET_KEY = os.getenv("AUTHORITY_SECRET_KEY", _DEFAULT_AUTHORITY_KEY)

# Evidence 256-bit encryption key (AES-GCM)
# Derive a 32-byte key from EVIDENCE_ENCRYPTION_KEY env var or dev fallback
_RAW_EVID_KEY = os.getenv("EVIDENCE_ENCRYPTION_KEY", _DEFAULT_EVIDENCE_KEY)
EVIDENCE_AES_KEY = hashlib.sha256(_RAW_EVID_KEY.encode("utf-8")).digest()


def _validate_production_config() -> None:
    """Fail closed: refuse to boot in production with insecure/missing secrets.

    Local development (ENVIRONMENT unset or 'development') keeps the documented
    fallbacks so the app runs out of the box. Production (ENVIRONMENT=production)
    requires every sensitive value to be explicitly configured.
    """
    if not IS_PRODUCTION:
        return
    missing = []
    if not JWT_SECRET or JWT_SECRET in _INSECURE_JWT_SECRETS:
        missing.append("JWT_SECRET")
    if AUTHORITY_SECRET_KEY == _DEFAULT_AUTHORITY_KEY or not AUTHORITY_SECRET_KEY:
        missing.append("AUTHORITY_SECRET_KEY")
    if _RAW_EVID_KEY == _DEFAULT_EVIDENCE_KEY or not _RAW_EVID_KEY:
        missing.append("EVIDENCE_ENCRYPTION_KEY")
    if not CLERK_ISSUER:
        missing.append("CLERK_ISSUER")
    if not CLERK_JWKS_URL:
        missing.append("CLERK_JWKS_URL")
    if missing:
        raise RuntimeError(
            "HAVEN refuses to start in production with insecure or missing secrets: "
            + ", ".join(missing)
            + ". Set these environment variables (see .env.example). "
            "Secret values are never logged."
        )


_validate_production_config()


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
    """Individual authority login (P1-7).

    Login identity is the `badge_number` (the officer's unique username) plus the
    officer's own `password`. `station`/`officer_name` are accepted for backward
    compatibility with older clients but are IGNORED for authentication and
    identity — the authenticated identity is read from the server-side authority
    record, never from these client-supplied fields.
    """
    password: str
    badge_number: Optional[str] = None
    # Ignored for auth/identity — retained only so old request bodies don't 422.
    station: Optional[str] = None
    officer_name: Optional[str] = None


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

    Security model:
      1. Haven-internal HS256 tokens (issued by our own authority/user login) are the ONLY
         source of elevated roles. They are verified against JWT_SECRET with a fixed issuer.
      2. Clerk (external) RS256 tokens are cryptographically verified against Clerk's JWKS
         when CLERK_ISSUER / CLERK_JWKS_URL is configured. A verified Clerk token may carry
         an elevated role only via trusted metadata.
      3. If a token is neither a valid internal token nor a verifiable Clerk token:
           - STRICT_AUTH=true  -> reject (401)
           - STRICT_AUTH=false -> accept as an unprivileged "user" for identity only.
             It can NEVER yield an authority/admin role. (dev convenience)

    This closes the previous bypass where any token with a forged `role` claim was trusted.
    """
    # 1. Internal Haven token (trusted for elevated roles)
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], issuer="haven-backend")
    except jwt.ExpiredSignatureError:
        raise _auth_error("internal_expired")
    except jwt.InvalidIssuerError:
        pass  # not an internal token — try Clerk below
    except jwt.PyJWTError:
        pass  # signature/format mismatch for internal — try Clerk below

    # 2. Clerk token, cryptographically verified against JWKS (if configured)
    try:
        verified = _verify_clerk_token(token)
    except jwt.ExpiredSignatureError:
        raise _auth_error("clerk_expired")
    except jwt.PyJWTError:
        # Token claims to be from Clerk but fails verification -> definitively invalid.
        # (Raw library text, key IDs and issuer details are never returned.)
        raise _auth_error("clerk_invalid")
    except Exception:
        # JWKS fetch / network / config problem — this is NOT a statement about
        # the token's validity, so fall through to the unverifiable path instead
        # of leaking a 500 or internal error text.
        logger.warning("Auth: Clerk verification unavailable (reason=jwks_unavailable)")
        verified = None

    if verified is not None:
        user_id = verified.get("sub") or verified.get("user_id") or "user"
        return {
            "sub": user_id,
            "user_id": user_id,
            "role": _extract_role(verified),  # trusted: signature was verified
            "email": verified.get("email"),
            "name": verified.get("name") or verified.get("first_name"),
            "exp": verified.get("exp"),
            "_verified": True,
        }

    # 3. Unverifiable token (no JWKS configured, not an internal token)
    if STRICT_AUTH:
        # Do not disclose which verification mechanism is (un)configured.
        raise _auth_error("unverifiable_strict")
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        raise _auth_error("malformed_claims")
    user_id = unverified.get("sub") or unverified.get("user_id") or "user"
    # CRITICAL: never honor a role claim from an unverified token — force plain user.
    return {
        "sub": user_id,
        "user_id": user_id,
        "role": "user",
        "email": unverified.get("email"),
        "name": unverified.get("name"),
        "exp": unverified.get("exp"),
        "_verified": False,
    }


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


_ELEVATED_ROLES = ("admin", "authority", "police", "protection_officer")


def require_user_or_self(target_user_id: str, current_user: AuthUser) -> bool:
    """Ensures a user can only access their own data unless they are an admin."""
    if current_user.role == "admin" or current_user.user_id == target_user_id:
        return True
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access forbidden: You cannot access or modify records belonging to another user.",
    )


def require_self_or_authority(target_user_id: str, current_user: AuthUser) -> bool:
    """Allow access only to the resource owner, or to an authority/admin.

    `current_user` must be a VERIFIED AuthUser (obtained via get_current_user),
    so unauthenticated callers never reach this check. Raises 403 otherwise.
    """
    if current_user.role in _ELEVATED_ROLES:
        return True
    if current_user.user_id == target_user_id:
        return True
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access forbidden: You cannot access records belonging to another user.",
    )


def verify_authority_password(plain_password: str) -> bool:
    """DEPRECATED shared-password check — retained only for backward compatibility.

    As of P1-7 authority login uses INDIVIDUAL credentials (see
    services.authority_service). This shared-secret comparison is NO LONGER used
    by any login route; it is kept because older modules/tests still import it.
    Do not reintroduce it as the authority login credential.
    """
    return hmac.compare_digest(plain_password.strip(), AUTHORITY_SECRET_KEY.strip())


# ─── Individual Credential Password Hashing (PBKDF2, no normalization) ─────

def hash_password(password: str, salt: Optional[str] = None) -> Dict[str, str]:
    """Hash an account password with PBKDF2-HMAC-SHA256 (100k iterations, random salt).

    Unlike hash_safe_word_salted (which normalizes case/punctuation for spoken
    safe-words), passwords are hashed VERBATIM so they stay case-sensitive and
    high-entropy. Returns {'hash', 'salt'} in hex. Never stores plaintext.
    """
    if not isinstance(password, str) or password == "":
        raise ValueError("password must be a non-empty string")
    if not salt:
        salt_bytes = secrets.token_bytes(16)
        salt_hex = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt)
        salt_hex = salt
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 100000, dklen=32)
    return {"hash": key.hex(), "salt": salt_hex}


def verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    """Constant-time verification of a password against a stored PBKDF2 hash+salt."""
    if not isinstance(password, str) or not stored_hash or not salt_hex:
        return False
    try:
        salt_bytes = bytes.fromhex(salt_hex)
    except Exception:
        return False
    calculated = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, 100000, dklen=32
    ).hex()
    return hmac.compare_digest(calculated, stored_hash)


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
