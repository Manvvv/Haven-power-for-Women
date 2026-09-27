"""Authentication routes for Haven."""
import logging
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from auth import (
    AuthUser, TokenResponse, AuthorityLoginModel,
    create_access_token, JWT_EXPIRATION_HOURS,
)
from services.authority_service import authenticate_authority, ensure_dev_authority
from services.audit_service import log_audit
from rate_limiter import rate_limit_dependency

logger = logging.getLogger("haven_backend")
router = APIRouter(tags=["Authentication"])


@router.post("/auth/authority-login", response_model=TokenResponse)
def authority_login(
    payload: AuthorityLoginModel,
    _=Depends(rate_limit_dependency(max_requests=5, window_seconds=60))
):
    """Authenticate an INDIVIDUAL authority officer against a server-side record.

    P1-7: replaces the previous shared-password login. The submitted
    `badge_number` (the officer's username) + `password` are verified against the
    officer's stored PBKDF2 hash. The authenticated identity embedded in the
    issued token — user_id, name, role — is read ENTIRELY from the verified
    server-side record. Client-supplied `officer_name`/`station`/`role` fields are
    ignored for identity, so a caller cannot impersonate another officer or
    elevate their role by editing the request body.
    """
    # Non-production convenience: make sure a local dev authority exists.
    ensure_dev_authority()

    record, error = authenticate_authority(payload.badge_number, payload.password)
    if error in ("not_found", "bad_password"):
        # Uniform 401 for both — never reveal whether the badge exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authority credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if error == "inactive":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This authority account is inactive. Contact an administrator.",
        )

    # Identity is derived from the verified record, NOT from the request body.
    authority_id = record["authority_id"]
    officer_name = record["officer_name"]
    role = record.get("role", "authority")

    token = create_access_token(
        user_id=authority_id,
        role=role,
        name=officer_name,
        expires_delta=timedelta(hours=JWT_EXPIRATION_HOURS),
    )
    # Audit the login with the verified identity (never the client-supplied fields).
    try:
        log_audit(authority_id, role, "AUTHORITY_LOGIN",
                  metadata={"badge_number": record["badge_number"], "officer_name": officer_name})
    except Exception:
        pass

    return TokenResponse(
        access_token=token, token_type="bearer",
        role=role, user_id=authority_id,
        expires_in=JWT_EXPIRATION_HOURS * 3600,
    )
