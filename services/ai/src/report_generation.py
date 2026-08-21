from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr, ValidationError

from .report_schemas import (
    PROMPT_VERSION,
    RecoveryActionSelectionRequest,
    RecoveryActionSelectionResponse,
    RecoveryReportCopy,
    RecoveryReportGenerationRequest,
    RecoveryReportGenerationResponse,
)

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"

SYSTEM_INSTRUCTION = """\
당신은 비의료적 생활 리포트의 한국어 문장 편집기입니다.
제공된 수치를 다시 계산하거나 변경하지 마세요.
제공되지 않은 원인, 사건, 감정 또는 사용자 상황을 추측하지 마세요.
의료적 진단, 질환명, 치료, 처방 표현을 사용하지 마세요.
selected_actions에 없는 행동을 추천하지 마세요.
changed_items와 recommendation_descriptions의 식별자와 순서를 바꾸지 마세요.
부드럽고 비판단적인 존댓말을 사용하고 지정된 JSON 형식으로만 응답하세요.
"""

_BANNED_TERMS = (
    "진단",
    "질환",
    "치료",
    "처방",
    "우울증",
    "불안장애",
    "공황장애",
)

_COPY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "headline",
        "summary",
        "weekly_observation",
        "changed_items",
        "recommendation_intro",
        "recommendation_descriptions",
    ],
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "weekly_observation": {"type": "string"},
        "changed_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["factor_code", "title", "description"],
                "properties": {
                    "factor_code": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "recommendation_intro": {"type": "string"},
        "recommendation_descriptions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action_id", "reason"],
                "properties": {
                    "action_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}

_ACTION_SELECTION_SCHEMA: dict[str, Any] = {
    "type": "array",
    "minItems": 1,
    "maxItems": 3,
    "items": {"type": "string"},
}


class RecoveryReportGenerationError(RuntimeError):
    """Gemini could not produce a usable recovery report."""


class RecoveryReportNotConfiguredError(RecoveryReportGenerationError):
    """Gemini report generation is disabled because no API key is configured."""


@dataclass(frozen=True)
class GeminiReportSettings:
    api_key: SecretStr | None
    model_name: str
    timeout_seconds: float
    prompt_version: str = PROMPT_VERSION

    @classmethod
    def from_env(cls) -> GeminiReportSettings:
        raw_key = os.getenv("GEMINI_API_KEY", "").strip()
        model_name = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
        if not model_name or "/" in model_name or any(
            character.isspace() for character in model_name
        ):
            raise ValueError("GEMINI_MODEL must be a non-empty model id")
        raw_timeout = os.getenv("GEMINI_TIMEOUT_SECONDS", "20")
        timeout_seconds = float(raw_timeout)
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("GEMINI_TIMEOUT_SECONDS must be in (0, 120]")
        prompt_version = os.getenv(
            "REPORT_PROMPT_VERSION",
            PROMPT_VERSION,
        ).strip()
        if prompt_version != PROMPT_VERSION:
            raise ValueError(
                "REPORT_PROMPT_VERSION does not match the compiled contract"
            )
        return cls(
            api_key=SecretStr(raw_key) if raw_key else None,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            prompt_version=prompt_version,
        )


class GeminiRecoveryReportGenerator:
    def __init__(
        self,
        settings: GeminiReportSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if http_client is not None and transport is not None:
            raise ValueError("provide either http_client or transport")
        self._settings = settings
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(transport=transport)

    @property
    def is_configured(self) -> bool:
        return self._settings.api_key is not None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(
        self,
        request: RecoveryReportGenerationRequest,
    ) -> RecoveryReportGenerationResponse:
        if self._settings.api_key is None:
            raise RecoveryReportNotConfiguredError(
                "Gemini report generation is not configured"
            )
        if request.prompt_version != self._settings.prompt_version:
            raise RecoveryReportGenerationError(
                "report prompt version does not match runtime configuration"
            )

        encoded_model = quote(self._settings.model_name, safe="-_.")
        url = (
            f"{GEMINI_API_BASE_URL}/models/{encoded_model}:generateContent"
        )
        prompt_payload = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload = {
            "systemInstruction": {
                "parts": [{"text": SYSTEM_INSTRUCTION}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_payload}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseJsonSchema": _COPY_SCHEMA,
            },
        }
        try:
            response = await self._client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": (
                        self._settings.api_key.get_secret_value()
                    ),
                },
                json=payload,
                timeout=self._settings.timeout_seconds,
            )
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise RecoveryReportGenerationError(
                "Gemini report generation request failed"
            ) from exc

        try:
            response_payload = response.json()
            parts = response_payload["candidates"][0]["content"]["parts"]
            raw_text = "".join(part["text"] for part in parts)
            copy = RecoveryReportCopy.model_validate_json(raw_text)
            copy.validate_against(request)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise RecoveryReportGenerationError(
                "Gemini returned an invalid structured report"
            ) from exc

        serialized_copy = json.dumps(
            copy.model_dump(mode="json"),
            ensure_ascii=False,
        )
        if any(term in serialized_copy for term in _BANNED_TERMS):
            raise RecoveryReportGenerationError(
                "Gemini report contains prohibited medical language"
            )

        return RecoveryReportGenerationResponse(
            **copy.model_dump(),
            model_name=self._settings.model_name,
            prompt_version=request.prompt_version,
        )

    async def select_actions(
        self,
        request: RecoveryActionSelectionRequest,
    ) -> RecoveryActionSelectionResponse:
        if self._settings.api_key is None:
            raise RecoveryReportNotConfiguredError(
                "Gemini action selection is not configured"
            )
        candidate_ids = {candidate.id for candidate in request.candidates}
        prompt_payload = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        system_instruction = (
            "당신은 회복 행동 우선순위 선택기입니다. "
            "후보 풀의 id 중에서만 1~3개를 우선순위 순서로 선택하세요. "
            "설명, 마크다운, 새 id를 출력하지 말고 JSON 문자열 배열만 출력하세요."
        )
        encoded_model = quote(self._settings.model_name, safe="-_.")
        url = f"{GEMINI_API_BASE_URL}/models/{encoded_model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": prompt_payload}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseJsonSchema": _ACTION_SELECTION_SCHEMA,
            },
        }
        try:
            response = await self._client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self._settings.api_key.get_secret_value(),
                },
                json=payload,
                timeout=self._settings.timeout_seconds,
            )
            response.raise_for_status()
            response_payload = response.json()
            parts = response_payload["candidates"][0]["content"]["parts"]
            raw_text = "".join(part["text"] for part in parts)
            ids = json.loads(raw_text)
            if (
                not isinstance(ids, list)
                or not 1 <= len(ids) <= 3
                or len(set(ids)) != len(ids)
                or any(not isinstance(item, str) or item not in candidate_ids for item in ids)
            ):
                raise ValueError("invalid recovery action ids")
            return RecoveryActionSelectionResponse(ids=ids)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise RecoveryReportGenerationError(
                "Gemini recovery action selection request failed"
            ) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RecoveryReportGenerationError(
                "Gemini returned invalid recovery action ids"
            ) from exc


__all__ = [
    "DEFAULT_GEMINI_MODEL",
    "GEMINI_API_BASE_URL",
    "GeminiRecoveryReportGenerator",
    "GeminiReportSettings",
    "RecoveryReportGenerationError",
    "RecoveryReportNotConfiguredError",
]
