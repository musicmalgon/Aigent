from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy.engine import Engine

from app.admin import UserAdmin
from app.api import auth, users
from app.core.config import Settings, settings
from app.core.database import create_database_engine
from app.models import user  # noqa: F401


def create_app(
    runtime_settings: Settings = settings,
    *,
    admin_engine: Engine | None = None,
) -> FastAPI:
    application = FastAPI(title="Re:Mind API")

    if runtime_settings.sqladmin_enabled:
        selected_engine = admin_engine or create_database_engine(
            runtime_settings.database_url
        )
        admin = Admin(
            application,
            selected_engine,
            base_url=runtime_settings.sqladmin_path,
        )
        admin.add_view(UserAdmin)

    application.include_router(auth.router)
    application.include_router(users.router, tags=["users"])

    @application.get("/")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health")
    def application_health() -> dict[str, str]:
        return {"status": "ok", "database": "not_checked"}

    return application


app = create_app()
