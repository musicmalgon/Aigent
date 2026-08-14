from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth import oauth
from app.core.security import create_access_token
from app.models.user import User

router = APIRouter(prefix="/auth/google", tags=["auth"])


@router.get("/login")
async def google_login(request: Request) -> RedirectResponse:
    return await oauth.google.authorize_redirect(
        request,
        settings.google_redirect_uri,
        access_type="offline",
        prompt="consent",
    )


@router.get("/callback")
async def google_callback(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await oauth.google.userinfo(token=token)

    google_sub = userinfo["sub"]
    email = userinfo["email"]

    user = db.query(User).filter(User.google_sub == google_sub).first()
    if not user:
        # 같은 이메일로 이미 (비밀번호) 가입된 계정이 있으면 그 계정에 연결
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(email=email, google_sub=google_sub)
            db.add(user)
        else:
            user.google_sub = google_sub

    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expires_at = token.get("expires_at")

    if access_token:
        user.google_access_token = access_token
    if refresh_token:
        user.google_refresh_token = refresh_token
    if expires_at:
        user.google_token_expiry = datetime.fromtimestamp(expires_at, tz=UTC)

    db.commit()
    db.refresh(user)

    jwt_token = create_access_token(subject=str(user.id))
    redirect_url = f"{settings.google_oauth_frontend_redirect_url}?token={jwt_token}"
    return RedirectResponse(url=redirect_url)