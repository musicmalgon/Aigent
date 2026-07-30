from __future__ import annotations

from ai.src.api import create_app
from ai.src.report_schemas import (
    RecoveryReportGenerationRequest,
    RecoveryReportGenerationResponse,
)
from fastapi.testclient import TestClient

from .test_recovery_report_generation import (
    copy_payload,
    generation_request,
)


class _LoadedEmotionService:
    is_loaded = True

    def load(self) -> None:
        pass

    def predict(self, request: object) -> object:
        raise AssertionError(request)


class _ReportGenerator:
    def __init__(self, *, configured: bool) -> None:
        self.is_configured = configured
        self.calls = 0

    async def generate(
        self,
        request: RecoveryReportGenerationRequest,
    ) -> RecoveryReportGenerationResponse:
        self.calls += 1
        return RecoveryReportGenerationResponse(
            **copy_payload(),
            model_name="gemini-test",
            prompt_version=request.prompt_version,
        )

    async def aclose(self) -> None:
        pass


def test_recovery_report_endpoint_returns_structured_response() -> None:
    generator = _ReportGenerator(configured=True)
    with TestClient(
        create_app(
            analyzer=_LoadedEmotionService(),
            report_generator=generator,
        )
    ) as client:
        response = client.post(
            "/v1/recovery-reports/generate",
            json=generation_request().model_dump(mode="json"),
        )

    assert response.status_code == 200
    assert response.json()["model_name"] == "gemini-test"
    assert generator.calls == 1


def test_recovery_report_endpoint_is_unavailable_without_api_key() -> None:
    generator = _ReportGenerator(configured=False)
    with TestClient(
        create_app(
            analyzer=_LoadedEmotionService(),
            report_generator=generator,
        )
    ) as client:
        response = client.post(
            "/v1/recovery-reports/generate",
            json=generation_request().model_dump(mode="json"),
        )

    assert response.status_code == 503
    assert generator.calls == 0
