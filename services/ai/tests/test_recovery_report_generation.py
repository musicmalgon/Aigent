from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from ai.src.report_generation import (
    DEFAULT_GEMINI_MODEL,
    GeminiRecoveryReportGenerator,
    GeminiReportSettings,
    RecoveryReportGenerationError,
    RecoveryReportNotConfiguredError,
)
from ai.src.report_schemas import (
    RecoveryAction,
    RecoveryReportChange,
    RecoveryReportGenerationRequest,
    RecoveryReportGenerationResponse,
    RecoveryReportPeriod,
)
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import SecretStr

CONTRACT_ROOT = (
    Path(__file__).resolve().parents[3] / "packages" / "contracts" / "schemas"
)


def generation_request() -> RecoveryReportGenerationRequest:
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
                factor_code="sleep_decrease",
                metric="sleep_minutes",
                recent_value=300,
                baseline_value=420,
                delta=-120,
                change_percent=-28.57,
                sample_days=7,
                fact_text=(
                    "최근 7일 중 7일 평균 수면 시간은 300분이고 "
                    "평소 기준은 420분입니다."
                ),
            )
        ],
        selected_actions=[
            RecoveryAction(
                id="SLEEP_EARLY_60",
                title="잠드는 시간을 조금 앞당기기",
                duration_minutes=60,
                difficulty="medium",
            )
        ],
        prompt_version="recovery-report-prompt-v1",
    )


def copy_payload() -> dict[str, Any]:
    return {
        "headline": "수면 리듬을 함께 살펴봤어요.",
        "summary": "최근 수면 시간이 평소 기준보다 줄어든 흐름이 보여요.",
        "weekly_observation": "제공된 7일 기록에서 수면 변화가 확인됐어요.",
        "changed_items": [
            {
                "factor_code": "sleep_decrease",
                "title": "수면 시간이 줄었어요",
                "description": "제공된 수면 기록이 평소 기준보다 낮았어요.",
            }
        ],
        "recommendation_intro": "부담이 적은 한 가지부터 시작해 보세요.",
        "recommendation_descriptions": [
            {
                "action_id": "SLEEP_EARLY_60",
                "reason": "선택된 수면 행동을 가볍게 시도해 볼 수 있어요.",
            }
        ],
    }


def test_gemini_settings_use_supported_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    settings = GeminiReportSettings.from_env()

    assert settings.model_name == DEFAULT_GEMINI_MODEL
    assert settings.model_name == "gemini-3.1-flash-lite"


def test_shared_contracts_validate_pydantic_payloads() -> None:
    request = generation_request()
    response = RecoveryReportGenerationResponse(
        **copy_payload(),
        model_name="gemini-test",
        prompt_version="recovery-report-prompt-v1",
    )
    request_schema = json.loads(
        (
            CONTRACT_ROOT / "recovery_report_generation_request.schema.json"
        ).read_text(encoding="utf-8")
    )
    response_schema = json.loads(
        (
            CONTRACT_ROOT / "recovery_report_generation_response.schema.json"
        ).read_text(encoding="utf-8")
    )

    Draft202012Validator(request_schema).validate(
        request.model_dump(mode="json")
    )
    Draft202012Validator(response_schema).validate(
        response.model_dump(mode="json")
    )


def test_gemini_request_uses_structured_output_and_validates_ids() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["api_key"] = request.headers["x-goog-api-key"]
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        copy_payload(),
                                        ensure_ascii=False,
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    generator = GeminiRecoveryReportGenerator(
        GeminiReportSettings(
            api_key=SecretStr("private-test-key"),
            model_name="gemini-test",
            timeout_seconds=5,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = asyncio.run(generator.generate(generation_request()))
    finally:
        asyncio.run(generator.aclose())

    assert result.model_name == "gemini-test"
    assert observed["api_key"] == "private-test-key"
    assert observed["url"].endswith(
        "/models/gemini-test:generateContent"
    )
    config = observed["payload"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"]["additionalProperties"] is False


def test_gemini_rejects_prohibited_language_and_missing_configuration() -> None:
    unsafe = copy_payload()
    unsafe["summary"] = "이 기록으로 질환을 진단할 수 있어요."

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        unsafe,
                                        ensure_ascii=False,
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    configured = GeminiRecoveryReportGenerator(
        GeminiReportSettings(
            api_key=SecretStr("private-test-key"),
            model_name="gemini-test",
            timeout_seconds=5,
        ),
        transport=httpx.MockTransport(handler),
    )
    missing = GeminiRecoveryReportGenerator(
        GeminiReportSettings(
            api_key=None,
            model_name="gemini-test",
            timeout_seconds=5,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RecoveryReportGenerationError):
            asyncio.run(configured.generate(generation_request()))
        with pytest.raises(RecoveryReportNotConfiguredError):
            asyncio.run(missing.generate(generation_request()))
    finally:
        asyncio.run(configured.aclose())
        asyncio.run(missing.aclose())
