from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqladmin import Admin
from sqlalchemy.engine import Engine

from app.admin import UserAdmin
from app.api import (
    auth,
    baselines,
    behavioral_records,
    emotion_analyses,
    risk_evaluations,
    users,
)
from app.clients.ai import AIServiceClient, create_ai_service_client
from app.core.config import Settings, settings
from app.core.database import create_database_engine
from app.models import user  # noqa: F401


def _create_lifespan(
    runtime_settings: Settings,
    injected_ai_client: AIServiceClient | None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        ai_client = injected_ai_client or create_ai_service_client(runtime_settings)
        application.state.ai_service_client = ai_client
        try:
            yield
        finally:
            if injected_ai_client is None:
                await ai_client.aclose()

    return lifespan


def create_app(
    runtime_settings: Settings = settings,
    *,
    admin_engine: Engine | None = None,
    ai_service_client: AIServiceClient | None = None,
) -> FastAPI:
    application = FastAPI(
        title="Re:Mind API",
        lifespan=_create_lifespan(runtime_settings, ai_service_client),
    )

    @application.exception_handler(RequestValidationError)
    async def safe_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        detail = [
            {
                "type": error["type"],
                "loc": error["loc"],
                "msg": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": detail},
        )

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
    application.include_router(behavioral_records.router)
    application.include_router(emotion_analyses.router)
    application.include_router(baselines.router)
    application.include_router(risk_evaluations.router)

    @application.get("/")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health")
    def application_health() -> dict[str, str]:
        return {"status": "ok", "database": "not_checked"}

    return application


app = create_app()
