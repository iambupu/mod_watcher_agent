"""Auth endpoints for token-based session login/logout."""

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from app.security import _load_runtime_policy

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(body: dict = Body(...)):
    """Validate token and set httpOnly session cookie."""
    token = str(body.get("token", "")).strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    policy = _load_runtime_policy()
    if not policy.admin_token:
        raise HTTPException(status_code=503, detail="MW_ADMIN_TOKEN is not configured on this instance")

    if token != policy.admin_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    response = JSONResponse(content={"status": "authenticated"})
    response.set_cookie(
        key="mw_session",
        value=policy.admin_token,
        httponly=True,
        samesite="strict",
        max_age=86400 * 30,  # 30 days
        path="/",
    )
    return response


@router.post("/logout")
async def logout():
    """Clear the session cookie."""
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie(key="mw_session", path="/")
    return response


@router.get("/status")
async def auth_status(request: Request):
    """Check whether the current request is authenticated."""
    cookie_token = request.cookies.get("mw_session", "").strip()
    if not cookie_token:
        return {"authenticated": False}

    policy = _load_runtime_policy()
    if policy.admin_token and cookie_token == policy.admin_token:
        return {"authenticated": True}
    return {"authenticated": False}
