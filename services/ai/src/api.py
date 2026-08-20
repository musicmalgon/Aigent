"""Minimal FastAPI boundary for coarse emotion inference."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from .emotion import (
    BurnoutSignalSettings,
    BurnoutSignalTransformerAnalyzer,
    CoarseEmotionSettings,
    CoarseTransformerEmotionAnalyzer,
    NeutralGateAnalyzer,
    NeutralGatedEmotionAnalyzer,
    NeutralGateSettings,
)
from .emotion.base import ModelNotReadyError, PredictionError
from .report_generation import (
    GeminiRecoveryReportGenerator,
    GeminiReportSettings,
    RecoveryReportGenerationError,
    RecoveryReportNotConfiguredError,
)
from .report_schemas import (
    RecoveryActionSelectionRequest,
    RecoveryActionSelectionResponse,
    RecoveryReportGenerationRequest,
    RecoveryReportGenerationResponse,
)
from .schemas import (
    BurnoutSignalInferenceResponse,
    CoarseEmotionInput,
    RemindCoarseEmotionInferenceResponse,
)

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


class BurnoutSignalService(Protocol):
    @property
    def is_loaded(self) -> bool: ...

    def load(self) -> None: ...

    def predict(self, request: CoarseEmotionInput) -> BurnoutSignalInferenceResponse: ...


def create_app(
    *,
    analyzer: CoarseEmotionService | None = None,
    settings: CoarseEmotionSettings | None = None,
    neutral_gate_settings: NeutralGateSettings | None = None,
    burnout_analyzer: BurnoutSignalService | None = None,
    burnout_settings: BurnoutSignalSettings | None = None,
    report_generator: RecoveryReportService | None = None,
) -> FastAPI:
    """Create an app whose liveness is independent from model readiness."""

    service = analyzer
    if service is None:
        coarse = CoarseTransformerEmotionAnalyzer(
            settings or CoarseEmotionSettings.from_env()
        )
        gate_settings = neutral_gate_settings or NeutralGateSettings.from_env()
        gate = (
            NeutralGateAnalyzer(
                artifact_dir=gate_settings.artifact_dir,
                device=gate_settings.device,
                max_length=gate_settings.max_length,
                threshold_override=gate_settings.threshold_override,
                model_version_override=gate_settings.model_version_override,
            )
            if gate_settings.enabled
            else None
        )
        service = NeutralGatedEmotionAnalyzer(
            coarse,
            gate,
            threshold_version=gate_settings.threshold_version,
        )
    generator = report_generator or GeminiRecoveryReportGenerator(
        GeminiReportSettings.from_env()
    )
    owns_generator = report_generator is None
    signal_settings = burnout_settings or BurnoutSignalSettings.from_env()
    signal_service = burnout_analyzer
    signal_enabled = signal_service is not None or signal_settings.enabled
    if signal_service is None and signal_enabled:
        signal_service = BurnoutSignalTransformerAnalyzer(signal_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        app.state.model_startup_error = None
        app.state.burnout_signal_startup_error = None
        if not service.is_loaded:
            try:
                service.load()
            except ModelNotReadyError as exc:
                app.state.model_startup_error = type(exc).__name__
                LOGGER.warning(
                    "coarse emotion model is not ready at startup: %s",
                    type(exc).__name__,
                )
        if signal_service is not None and not signal_service.is_loaded:
            try:
                signal_service.load()
            except ModelNotReadyError as exc:
                app.state.burnout_signal_startup_error = type(exc).__name__
                LOGGER.warning(
                    "burnout signal model is not ready at startup: %s",
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
    app.state.burnout_signal_analyzer = signal_service
    app.state.recovery_report_generator = generator

    @app.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def readiness() -> Any:
        if service.is_loaded:
            metadata = getattr(service, "readiness_metadata", {})
            return {"status": "ready", **metadata}
        metadata = getattr(service, "readiness_metadata", {})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", **metadata},
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
        "/v1/burnout-signals/analyze",
        response_model=BurnoutSignalInferenceResponse,
        tags=["burnout-signals"],
        summary="Analyze six independent non-diagnostic pattern signals",
    )
    def analyze_burnout_signals(
        request: CoarseEmotionInput,
    ) -> BurnoutSignalInferenceResponse:
        if signal_service is None or not signal_service.is_loaded:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="burnout signal model is not ready",
            )
        try:
            return signal_service.predict(request)
        except ModelNotReadyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="burnout signal model is not ready",
            ) from exc
        except PredictionError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="burnout signal inference failed",
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

    @app.post(
        "/v1/recovery-actions/select",
        response_model=RecoveryActionSelectionResponse,
        tags=["recovery-actions"],
        summary="Select fixed recovery action ids",
    )
    async def select_recovery_actions(
        request: RecoveryActionSelectionRequest,
    ) -> RecoveryActionSelectionResponse:
        if not generator.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="recovery action selection is not configured",
            )
        try:
            return await generator.select_actions(request)
        except RecoveryReportNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="recovery action selection is not configured",
            ) from exc
        except RecoveryReportGenerationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="recovery action selection failed",
            ) from exc

    return app


__all__ = [
    "BurnoutSignalService",
    "CoarseEmotionService",
    "RecoveryReportService",
    "create_app",
]
