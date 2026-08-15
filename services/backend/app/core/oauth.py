from authlib.integrations.starlette_client import OAuth

from app.core.config import settings

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=(
        settings.google_client_secret.get_secret_value()
        if settings.google_client_secret
        else None
    ),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile https://www.googleapis.com/auth/calendar.readonly",
        # refresh_token을 매번 받으려면 offline + consent 필요
        "access_type": "offline",
        "prompt": "consent",
    },
)