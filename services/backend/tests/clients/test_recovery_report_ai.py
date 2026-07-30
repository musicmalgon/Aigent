from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.clients.ai import (
    AIServiceClient,
    AIServiceClientConfig,
    AIServiceResponseValidationError,
)
from app.domain.recovery.models import (
    RecoveryAction,
    RecoveryActionId,
    RecoveryDifficulty,
    RecoveryReportChange,
    RecoveryReportGenerationRequest,
    RecoveryReportPeriod,
    ReportFactorCode,
    ReportMetric,
)


def request_model() -> RecoveryReportGenerationRequest:
    return RecoveryReportGenerationRequest(
        risk_level="moderate",
        risk_score=36.5,
        is_provisional=False,
        data_quality="sufficient",
        period=RecoveryReportPeriod(
            start=date(2026, 7, 14),
            end=date(2026, 7, 20),
            record_days=7,
        ),
        changes=[
            RecoveryReportChange(
                factor_code=ReportFactorCode.SLEEP_DECREASE,
                metric=ReportMetric.SLEEP_MINUTES,
                recent_value=300,
                baseline_value=420,
                delta=-120,
                change_percent=-28.57,
                sample_days=7,
                fact_text="합성 수면 변화",
            )
        ],
        selected_actions=[
            RecoveryAction(
                id=RecoveryActionId.SLEEP_EARLY_60,
                title="잠드는 시간을 조금 앞당기기",
                duration_minutes=60,
                difficulty=RecoveryDifficulty.MEDIUM,
            )
        ],
    )


def response_payload() -> dict[str, Any]:
    return {
        "headline": "수면 리듬을 살펴봤어요.",
        "summary": "제공된 기록에서 수면 변화가 보여요.",
        "weekly_observation": "최근 7일 기록을 평소 기준과 비교했어요.",
        "changed_items": [
            {
                "factor_code": "sleep_decrease",
                "title": "수면 시간이 줄었어요",
                "description": "제공된 수면 기록이 평소 기준보다 낮았어요.",
            }
        ],
        "recommendation_intro": "한 가지부터 시작해 보세요.",
        "recommendation_descriptions": [
            {
                "action_id": "SLEEP_EARLY_60",
                "reason": "선택된 행동을 가볍게 시도해 볼 수 있어요.",
            }
        ],
        "model_name": "gemini-test",
        "prompt_version": "recovery-report-prompt-v1",
    }


def config() -> AIServiceClientConfig:
    return AIServiceClientConfig(
        base_url="https://ai.internal/",
        connect_timeout_seconds=1,
        read_timeout_seconds=2,
        write_timeout_seconds=3,
        pool_timeout_seconds=4,
        auth_token=SecretStr("internal-token"),
    )


def test_recovery_report_client_serializes_and_validates_response() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json=response_payload(),
        )

    async def call() -> object:
        async with AIServiceClient(
            config(),
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.generate_recovery_report(request_model())

    result = asyncio.run(call())

    assert result.model_name == "gemini-test"
    assert observed["url"] == (
        "https://ai.internal/v1/recovery-reports/generate"
    )
    assert observed["json"]["selected_actions"][0]["id"] == "SLEEP_EARLY_60"


def test_recovery_report_client_rejects_changed_action_ids() -> None:
    invalid = response_payload()
    invalid["recommendation_descriptions"][0]["action_id"] = "REST_30"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=invalid)

    async def call() -> object:
        async with AIServiceClient(
            config(),
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.generate_recovery_report(request_model())

    with pytest.raises(AIServiceResponseValidationError):
        asyncio.run(call())
