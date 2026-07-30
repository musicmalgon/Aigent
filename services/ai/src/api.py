"""Minimal FastAPI boundary for coarse emotion inference."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from .emotion import CoarseEmotionSettings, CoarseTransformerEmotionAnalyzer
from .emotion.base import ModelNotReadyError, PredictionError
from .report_generation import (
    GeminiRecoveryReportGenerator,
    GeminiReportSettings,
    RecoveryReportGenerationError,
    RecoveryReportNotConfiguredError,
)
from .report_schemas import (
    RecoveryReportGenerationRequest,
    RecoveryReportGenerationResponse,
)
from .schemas import CoarseEmotionInput, RemindCoarseEmotionInferenceResponse

LOGGER = logging.getLogger(__name__)


class CoarseEmotionService(Protocol):
    @property
    def is_loaded(self) -> bool: ...

    def load(self) -> None: ...

    def predict(
        self, request: CoarseEmotionInput
    ) -> RemindCoarseEmotionInferenceResponse: ...


class RecoveryReportService(Protocol):
    @property
    def is_configured(self) -> bool: ...

    async def generate(
        self,
        request: RecoveryReportGenerationRequest,
    ) -> RecoveryReportGenerationResponse: ...

    async def aclose(self) -> None: ...


def create_app(
    *,
    analyzer: CoarseEmotionService | None = None,
    settings: CoarseEmotionSettings | None = None,
    report_generator: RecoveryReportService | None = None,
) -> FastAPI:
    """Create an app whose liveness is independent from model readiness."""

    service = analyzer
    if service is None:
        service = CoarseTransformerEmotionAnalyzer(
            settings or CoarseEmotionSettings.from_env()
        )
    generator = report_generator or GeminiRecoveryReportGenerator(
        GeminiReportSettings.from_env()
    )
    owns_generator = report_generator is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        app.state.model_startup_error = None
        if not service.is_loaded:
            try:
                service.load()
            except ModelNotReadyError as exc:
                app.state.model_startup_error = type(exc).__name__
                LOGGER.warning(
                    "coarse emotion model is not ready at startup: %s",
                    type(exc).__name__,
                )
        try:
            yield
        finally:
            if owns_generator:
                await generator.aclose()

    app = FastAPI(
        title="Re:Mind AI Service",
        version="1.0",
        description=(
            "Non-diagnostic emotion classification service. Outputs must not be "
            "used as medical diagnoses or treatment decisions."
        ),
        lifespan=lifespan,
    )
    app.state.coarse_emotion_analyzer = service
    app.state.recovery_report_generator = generator

    @app.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def readiness() -> Any:
        if service.is_loaded:
            return {"status": "ready"}
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready"},
        )

    @app.post(
        "/v2/emotions/classify",
        response_model=RemindCoarseEmotionInferenceResponse,
        tags=["emotions"],
        summary="Classify up to three user utterances into six coarse emotions",
    )
    def classify(request: CoarseEmotionInput) -> RemindCoarseEmotionInferenceResponse:
        if not service.is_loaded:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="emotion model is not ready",
            )
        try:
            return service.predict(request)
        except ModelNotReadyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="emotion model is not ready",
            ) from exc
        except PredictionError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="emotion inference failed",
            ) from exc

    @app.post(
        "/v1/recovery-reports/generate",
        response_model=RecoveryReportGenerationResponse,
        tags=["recovery-reports"],
        summary="Turn deterministic recovery facts into structured Korean copy",
    )
    async def generate_recovery_report(
        request: RecoveryReportGenerationRequest,
    ) -> RecoveryReportGenerationResponse:
        if not generator.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="recovery report generation is not configured",
            )
        try:
            return await generator.generate(request)
        except RecoveryReportNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="recovery report generation is not configured",
            ) from exc
        except RecoveryReportGenerationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="recovery report generation failed",
            ) from exc

    return app


__all__ = ["CoarseEmotionService", "RecoveryReportService", "create_app"]
