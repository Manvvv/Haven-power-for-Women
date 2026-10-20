"""Authentication routes for Haven."""
import logging
from datetime import timedelta
from fastapi import APIRouter, Body, Depends, HTTPException, status
from services import responder_service
from auth import (
    AuthUser, TokenResponse, AuthorityLoginModel,
    create_access_token, JWT_EXPIRATION_HOURS,
)
from services.authority_service import authenticate_authority, ensure_dev_authority
from services.responder_service import authenticate_responder, ensure_dev_responder
from models.schemas import ResponderLoginModel
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


@router.post("/auth/responder-setup")
def responder_setup_endpoint(
    body: dict = Body(...),
    _=Depends(rate_limit_dependency(max_requests=5, window_seconds=60)),
):
    """Redeem a single-use provider setup token and set the provider's own password.

    Not an account-creation path: the account already exists (created by an ADMIN),
    and this only sets its credential. The token is random, expires, and can be used
    once. Verification is NOT granted here — an admin must still verify the provider
    before any offer can reach them. Errors are deliberately uniform for invalid vs
    unknown tokens so token existence is not revealed.
    """
    token = str((body or {}).get("token") or (body or {}).get("setup_token") or "")
    password = (body or {}).get("password")
    if not token or len(token) > 200:
        raise HTTPException(status_code=422, detail="Invalid setup request.")
    rec, err = responder_service.consume_setup_token(token, password if isinstance(password, str) else "")
    if err == "weak_password":
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters.")
    if err in ("invalid", "used", "expired"):
        raise HTTPException(status_code=400, detail="This setup link is invalid, used, or has expired.")
    log_audit(actor_id=rec.get("responder_id"), role="responder", action="PROVIDER_PASSWORD_SET",
              metadata={"responder_id": rec.get("responder_id")})
    return {"success": True, "message": "Password set. An administrator must verify your account before you receive emergency requests."}


@router.post("/auth/responder-login", response_model=TokenResponse)
def responder_login(
    payload: ResponderLoginModel,
    _=Depends(rate_limit_dependency(max_requests=5, window_seconds=60))
):
    """Authenticate a FIELD RESPONDER against a server-side record (Rapid Response).

    Mirrors authority-login's security posture exactly: the `badge_number` + own
    `password` are verified against the responder's stored PBKDF2 hash, and the
    identity embedded in the issued token (user_id=responder_id, role="responder")
    is read ENTIRELY from the verified server-side record. No client field decides
    role or identity, so a caller cannot self-elevate to a responder or impersonate
    a unit. role="responder" grants ONLY the /responder/* + assigned-dispatch
    surface (require_responder); it is NOT an authority/admin role.

    Login succeeds for an active account even if not yet admin-verified, so the
    unit can see a "pending approval" state — but an unverified unit can never be
    offered or claim a dispatch (that gate lives in eligibility + the accept claim).
    """
    # Non-production convenience: make sure a local dev responder exists.
    ensure_dev_responder()

    record, error = authenticate_responder(payload.badge_number, payload.password)
    if error in ("not_found", "bad_password"):
        # Uniform 401 for both — never reveal whether the badge exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid responder credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if error == "inactive":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This responder account is inactive. Contact an administrator.",
        )

    # Identity is derived from the verified record, NOT from the request body.
    responder_id = record["responder_id"]
    role = "responder"  # fixed server-side; never from the client
    token = create_access_token(
        user_id=responder_id,
        role=role,
        name=record.get("display_label"),
        expires_delta=timedelta(hours=JWT_EXPIRATION_HOURS),
    )
    try:
        log_audit(responder_id, role, "RESPONDER_LOGIN",
                  metadata={"badge_number": record.get("badge_number"),
                            "verified": record.get("verified", False)})
    except Exception:
        pass

    return TokenResponse(
        access_token=token, token_type="bearer",
        role=role, user_id=responder_id,
        expires_in=JWT_EXPIRATION_HOURS * 3600,
    )
