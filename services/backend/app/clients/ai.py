"""Typed asynchronous client for the Re:Mind AI HTTP service."""

from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Annotated, Any, Literal, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictFloat,
    ValidationError,
    field_validator,
    model_validator,
)

from app.core.config import Settings
from app.domain.recovery.models import (
    RecoveryReportGenerationRequest,
    RecoveryReportGenerationResponse,
)

LOGGER = logging.getLogger(__name__)

CLASSIFY_ENDPOINT = "v2/emotions/classify"
BURNOUT_SIGNALS_ENDPOINT = "v1/burnout-signals/analyze"
REPORT_ENDPOINT = "v1/recovery-reports/generate"
LIVENESS_ENDPOINT = "health/live"
READINESS_ENDPOINT = "health/ready"


def _reject_non_json_integer(value: object) -> object:
    if isinstance(value, (bool, str, bytes, bytearray)):
        raise ValueError("integer fields require JSON integer values")
    return value


JsonInteger = Annotated[int, BeforeValidator(_reject_non_json_integer)]
Probability = Annotated[StrictFloat, Field(ge=0, le=1)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0)]
NonEmptyString = Annotated[str, Field(min_length=1)]


class _WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class CoarseEmotionLabel(StrEnum):
    ANGER = "분노"
    JOY = "기쁨"
    ANXIETY = "불안"
    EMBARRASSMENT = "당황"
    SADNESS = "슬픔"
    LETHARGY = "무기력"


COARSE_EMOTION_LABELS = tuple(CoarseEmotionLabel)
COARSE_EMOTION_LABEL_TO_ID = {
    label: index for index, label in enumerate(COARSE_EMOTION_LABELS)
}


class UncertaintyReason(StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    SMALL_MARGIN = "small_margin"
    LOW_CONFIDENCE_AND_SMALL_MARGIN = "low_confidence_and_small_margin"
    NEUTRAL_GATE = "neutral_gate"


class NeutralGateDecision(StrEnum):
    NEUTRAL = "neutral"
    EMOTIONAL = "emotional"


def _normalize_utterance(value: object, *, optional: bool) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("utterances must be strings")
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).strip())
    if not normalized:
        if optional:
            return None
        raise ValueError("required utterances must not be empty")
    return normalized


class CoarseEmotionRequest(_WireModel):
    """Wire request accepted by ``POST /v2/emotions/classify``."""

    hs01: Annotated[str, Field(min_length=1, max_length=2000)]
    hs02: Annotated[str, Field(min_length=1, max_length=2000)]
    hs03: Annotated[str, Field(min_length=1, max_length=2000)] | None = None

    @field_validator("hs01", "hs02", mode="before")
    @classmethod
    def normalize_required_utterance(cls, value: object) -> str:
        normalized = _normalize_utterance(value, optional=False)
        assert isinstance(normalized, str)
        return normalized

    @field_validator("hs03", mode="before")
    @classmethod
    def normalize_optional_utterance(cls, value: object) -> str | None:
        return _normalize_utterance(value, optional=True)


class CoarseEmotionTopPrediction(_WireModel):
    emotion: CoarseEmotionLabel
    label_id: Annotated[JsonInteger, Field(ge=0, le=5)]
    probability: Probability

    @model_validator(mode="after")
    def validate_label_id(self) -> CoarseEmotionTopPrediction:
        if self.label_id != COARSE_EMOTION_LABEL_TO_ID[self.emotion]:
            raise ValueError("label_id does not match emotion")
        return self


class CoarseEmotionResponse(_WireModel):
    """Validated Emotion Taxonomy v2 response from the AI service."""

    taxonomy_version: Literal["v2"]
    model_version: NonEmptyString
    threshold_version: NonEmptyString
    predicted_emotion: CoarseEmotionLabel | None
    predicted_label_id: Annotated[JsonInteger, Field(ge=0, le=5)] | None
    emotion: CoarseEmotionLabel | None
    confidence: Probability | None
    margin: Probability | None
    provisional: StrictBool
    is_uncertain: StrictBool
    uncertainty_reason: UncertaintyReason | None
    probabilities: (
        Annotated[
            dict[CoarseEmotionLabel, Probability],
            Field(min_length=6, max_length=6),
        ]
        | None
    )
    top_predictions: (
        Annotated[
            list[CoarseEmotionTopPrediction],
            Field(min_length=1, max_length=6),
        ]
        | None
    )
    neutral_gate_decision: NeutralGateDecision | None = None
    neutral_gate_score: Probability | None = None
    neutral_gate_model_version: NonEmptyString | None = None
    neutral_gate_threshold: Probability | None = None
    latency_ms: NonNegativeFloat

    @model_validator(mode="after")
    def validate_prediction_consistency(self) -> CoarseEmotionResponse:
        gate_values = (
            self.neutral_gate_decision,
            self.neutral_gate_score,
            self.neutral_gate_model_version,
            self.neutral_gate_threshold,
        )
        gate_configured = any(value is not None for value in gate_values)
        if gate_configured and any(value is None for value in gate_values):
            raise ValueError("neutral gate provenance must be complete")
        if self.neutral_gate_decision is NeutralGateDecision.NEUTRAL:
            assert self.neutral_gate_score is not None
            assert self.neutral_gate_threshold is not None
            if 1.0 - self.neutral_gate_score >= self.neutral_gate_threshold:
                raise ValueError("neutral gate decision does not match its threshold")
            if any(
                value is not None
                for value in (
                    self.predicted_emotion,
                    self.predicted_label_id,
                    self.emotion,
                    self.confidence,
                    self.margin,
                    self.probabilities,
                    self.top_predictions,
                )
            ):
                raise ValueError("neutral gate results cannot contain emotion output")
            if (
                not self.provisional
                or not self.is_uncertain
                or self.uncertainty_reason is not UncertaintyReason.NEUTRAL_GATE
            ):
                raise ValueError("neutral gate results must be provisional")
            return self
        if self.neutral_gate_decision is NeutralGateDecision.EMOTIONAL:
            assert self.neutral_gate_score is not None
            assert self.neutral_gate_threshold is not None
            if 1.0 - self.neutral_gate_score < self.neutral_gate_threshold:
                raise ValueError("emotional gate decision does not match its threshold")
        if any(
            value is None
            for value in (
                self.predicted_emotion,
                self.predicted_label_id,
                self.confidence,
                self.margin,
                self.probabilities,
                self.top_predictions,
            )
        ):
            raise ValueError("emotion output is required when the neutral gate passes")
        assert self.predicted_emotion is not None
        assert self.predicted_label_id is not None
        assert self.confidence is not None
        assert self.margin is not None
        assert self.probabilities is not None
        assert self.top_predictions is not None
        if set(self.probabilities) != set(COARSE_EMOTION_LABELS):
            raise ValueError("probabilities must contain exactly the six labels")
        probability_sum = sum(self.probabilities.values())
        if not math.isclose(probability_sum, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("probabilities must sum to one")

        ordered = sorted(
            self.probabilities.items(),
            key=lambda item: (-item[1], COARSE_EMOTION_LABEL_TO_ID[item[0]]),
        )
        winner, winner_probability = ordered[0]
        if self.predicted_emotion is not winner:
            raise ValueError("predicted_emotion must be the maximum probability label")
        if self.predicted_label_id != COARSE_EMOTION_LABEL_TO_ID[winner]:
            raise ValueError("predicted_label_id does not match predicted_emotion")
        if not math.isclose(
            self.confidence,
            winner_probability,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise ValueError("confidence must equal the maximum probability")

        if len({item.emotion for item in self.top_predictions}) != len(
            self.top_predictions
        ):
            raise ValueError("top_predictions must not contain duplicates")
        for index, prediction in enumerate(self.top_predictions):
            expected_label, expected_probability = ordered[index]
            if prediction.emotion is not expected_label or not math.isclose(
                prediction.probability,
                expected_probability,
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise ValueError("top_predictions must be sorted by probability")

        if self.is_uncertain != (self.uncertainty_reason is not None):
            raise ValueError("uncertainty_reason must match is_uncertain")
        if self.provisional != self.is_uncertain:
            raise ValueError("provisional must match is_uncertain")
        if self.uncertainty_reason is UncertaintyReason.NEUTRAL_GATE:
            raise ValueError("neutral_gate uncertainty requires a neutral decision")
        expected_emotion = None if self.provisional else winner
        if self.emotion is not expected_emotion:
            raise ValueError("emotion must be null exactly when provisional")

        expected_margin = ordered[0][1] - ordered[1][1]
        if not math.isclose(
            self.margin,
            expected_margin,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise ValueError("margin must equal the top-one/top-two difference")
        return self


class BurnoutSignalLabel(StrEnum):
    EXHAUSTION = "exhaustion"
    OVERLOAD = "overload"
    HELPLESSNESS = "helplessness"
    LOW_EFFICACY = "low_efficacy"
    ANXIETY = "anxiety"
    IRRITABILITY = "irritability"


BURNOUT_SIGNAL_LABELS = tuple(BurnoutSignalLabel)


class BurnoutSignalState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNVALIDATED = "unvalidated"


class BurnoutSignalResponse(_WireModel):
    taxonomy_version: Literal["stage2-burnout-signals-v1"]
    model_version: NonEmptyString
    threshold_version: NonEmptyString
    probabilities: Annotated[
        dict[BurnoutSignalLabel, Probability], Field(min_length=6, max_length=6)
    ]
    thresholds: Annotated[
        dict[BurnoutSignalLabel, Probability], Field(min_length=6, max_length=6)
    ]
    signal_states: Annotated[
        dict[BurnoutSignalLabel, BurnoutSignalState], Field(min_length=6, max_length=6)
    ]
    active_signals: list[BurnoutSignalLabel]
    validated_signals: list[BurnoutSignalLabel]
    deployment_status: Literal["shadow_only", "partial", "validated"]
    informational_only: Literal[True]
    risk_score_eligible: Literal[False]
    latency_ms: NonNegativeFloat

    @model_validator(mode="after")
    def validate_signal_consistency(self) -> BurnoutSignalResponse:
        expected = set(BURNOUT_SIGNAL_LABELS)
        if any(
            set(values) != expected
            for values in (self.probabilities, self.thresholds, self.signal_states)
        ):
            raise ValueError("all signal maps must contain exactly six labels")
        if len(self.active_signals) != len(set(self.active_signals)) or len(
            self.validated_signals
        ) != len(set(self.validated_signals)):
            raise ValueError("signal lists must not contain duplicates")
        active = set(self.active_signals)
        validated = set(self.validated_signals)
        if not active <= validated:
            raise ValueError("active signals must be validated")
        for label in BURNOUT_SIGNAL_LABELS:
            state = self.signal_states[label]
            if label not in validated:
                if state is not BurnoutSignalState.UNVALIDATED:
                    raise ValueError("unvalidated signals require unvalidated state")
                continue
            expected_state = (
                BurnoutSignalState.PRESENT
                if self.probabilities[label] >= self.thresholds[label]
                else BurnoutSignalState.ABSENT
            )
            if state is not expected_state or (
                label in active
            ) != (state is BurnoutSignalState.PRESENT):
                raise ValueError("signal state is inconsistent")
        expected_status = (
            "validated"
            if len(validated) == len(BURNOUT_SIGNAL_LABELS)
            else "partial" if validated else "shadow_only"
        )
        if self.deployment_status != expected_status:
            raise ValueError("deployment status is inconsistent")
        return self


class LivenessResponse(_WireModel):
    status: Literal["ok"]


class ReadinessResponse(_WireModel):
    status: Literal["ready", "not_ready"]
    neutral_gate_enabled: bool | None = None
    neutral_gate_model_version: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


class AIServiceError(Exception):
    """Base error containing only safe downstream metadata."""

    def __init__(
        self,
        message: str,
        *,
        endpoint: str,
        error_code: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.error_code = error_code
        self.status_code = status_code


class AIServiceConfigurationError(AIServiceError):
    pass


class AIServiceConnectionError(AIServiceError):
    pass


class AIServiceTimeoutError(AIServiceError):
    def __init__(self, *, endpoint: str, timeout_type: str) -> None:
        super().__init__(
            f"AI service {timeout_type} timeout",
            endpoint=endpoint,
            error_code="downstream_timeout",
        )
        self.timeout_type = timeout_type


class AIServiceHTTPError(AIServiceError):
    pass


class AIServiceClientResponseError(AIServiceHTTPError):
    pass


class AIServiceAuthenticationError(AIServiceClientResponseError):
    pass


class AIServiceServerResponseError(AIServiceHTTPError):
    pass


class AIServiceInvalidJSONError(AIServiceError):
    pass


class AIServiceResponseValidationError(AIServiceError):
    pass


@dataclass(frozen=True, slots=True)
class AIServiceClientConfig:
    base_url: str
    connect_timeout_seconds: float
    read_timeout_seconds: float
    write_timeout_seconds: float
    pool_timeout_seconds: float
    auth_token: SecretStr | None = None
    stage2_burnout_signals_enabled: bool = False

    def __post_init__(self) -> None:
        timeout_values = {
            "connect": self.connect_timeout_seconds,
            "read": self.read_timeout_seconds,
            "write": self.write_timeout_seconds,
            "pool": self.pool_timeout_seconds,
        }
        for timeout_name, value in timeout_values.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
                or value > 300
            ):
                raise AIServiceConfigurationError(
                    f"AI service {timeout_name} timeout is invalid",
                    endpoint="configuration",
                    error_code="invalid_timeout",
                )
        if self.auth_token is not None and not (
            self.auth_token.get_secret_value().strip()
        ):
            raise AIServiceConfigurationError(
                "AI service auth token is empty",
                endpoint="configuration",
                error_code="invalid_auth_token",
            )

    @classmethod
    def from_settings(cls, settings: Settings) -> AIServiceClientConfig:
        return cls(
            base_url=settings.ai_service_base_url,
            connect_timeout_seconds=settings.ai_service_connect_timeout_seconds,
            read_timeout_seconds=settings.ai_service_read_timeout_seconds,
            write_timeout_seconds=settings.ai_service_write_timeout_seconds,
            pool_timeout_seconds=settings.ai_service_pool_timeout_seconds,
            auth_token=settings.ai_service_auth_token,
            stage2_burnout_signals_enabled=settings.stage2_burnout_signals_enabled,
        )

    def to_httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect_timeout_seconds,
            read=self.read_timeout_seconds,
            write=self.write_timeout_seconds,
            pool=self.pool_timeout_seconds,
        )


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class AIServiceClient:
    """Reusable async client with explicit ownership and no automatic retry."""

    def __init__(
        self,
        config: AIServiceClientConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if http_client is not None and transport is not None:
            raise AIServiceConfigurationError(
                "provide either an HTTP client or a transport, not both",
                endpoint="configuration",
                error_code="conflicting_http_dependencies",
            )

        self._base_url = self._normalize_base_url(config.base_url)
        self._timeout = config.to_httpx_timeout()
        self._auth_token = config.auth_token
        self._stage2_burnout_signals_enabled = (
            config.stage2_burnout_signals_enabled
        )
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(transport=transport)
        self._closed = False

    @staticmethod
    def _normalize_base_url(value: str) -> httpx.URL:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            not normalized
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in normalized)
        ):
            raise AIServiceConfigurationError(
                "AI service base URL is invalid",
                endpoint="configuration",
                error_code="invalid_base_url",
            )
        return httpx.URL(f"{normalized}/")

    async def __aenter__(self) -> AIServiceClient:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        await self.aclose()

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def stage2_burnout_signals_enabled(self) -> bool:
        return self._stage2_burnout_signals_enabled

    async def aclose(self) -> None:
        if self._closed:
            return
        if self._owns_http_client:
            await self._http_client.aclose()
        self._closed = True

    async def classify_emotion(
        self,
        request: CoarseEmotionRequest,
    ) -> CoarseEmotionResponse:
        result, _ = await self._request_model(
            "POST",
            CLASSIFY_ENDPOINT,
            request_model=request,
            response_model=CoarseEmotionResponse,
            expected_statuses={200},
        )
        return result

    async def analyze_burnout_signals(
        self,
        request: CoarseEmotionRequest,
    ) -> BurnoutSignalResponse:
        result, _ = await self._request_model(
            "POST",
            BURNOUT_SIGNALS_ENDPOINT,
            request_model=request,
            response_model=BurnoutSignalResponse,
            expected_statuses={200},
        )
        return result

    async def generate_recovery_report(
        self,
        request: RecoveryReportGenerationRequest,
    ) -> RecoveryReportGenerationResponse:
        result, _ = await self._request_model(
            "POST",
            REPORT_ENDPOINT,
            request_model=request,
            response_model=RecoveryReportGenerationResponse,
            expected_statuses={200},
        )
        try:
            result.validate_against(request)
        except ValueError:
            raise AIServiceResponseValidationError(
                "AI service recovery report failed semantic validation",
                endpoint=REPORT_ENDPOINT,
                error_code="invalid_response_schema",
                status_code=200,
            ) from None
        return result

    async def check_liveness(self) -> LivenessResponse:
        result, _ = await self._request_model(
            "GET",
            LIVENESS_ENDPOINT,
            response_model=LivenessResponse,
            expected_statuses={200},
        )
        return result

    async def check_readiness(self) -> ReadinessResponse:
        result, status_code = await self._request_model(
            "GET",
            READINESS_ENDPOINT,
            response_model=ReadinessResponse,
            expected_statuses={200, 503},
        )
        status_matches_payload = (
            status_code == 200
            and result.status == "ready"
            or status_code == 503
            and result.status == "not_ready"
        )
        if not status_matches_payload:
            LOGGER.warning(
                "AI service readiness validation failed endpoint=%s status=%s "
                "error_code=%s",
                READINESS_ENDPOINT,
                status_code,
                "invalid_response_schema",
            )
            raise AIServiceResponseValidationError(
                "AI service readiness status is inconsistent",
                endpoint=READINESS_ENDPOINT,
                error_code="invalid_response_schema",
                status_code=status_code,
            )
        return result

    async def _request_model(
        self,
        method: str,
        endpoint: str,
        *,
        response_model: type[ResponseModel],
        expected_statuses: set[int],
        request_model: BaseModel | None = None,
    ) -> tuple[ResponseModel, int]:
        if self._closed:
            raise AIServiceConfigurationError(
                "AI service client is closed",
                endpoint=endpoint,
                error_code="client_closed",
            )

        url = self._base_url.join(endpoint)
        headers = {"Accept": "application/json"}
        if self._auth_token is not None:
            headers["Authorization"] = f"Bearer {self._auth_token.get_secret_value()}"
        request_json = (
            request_model.model_dump(mode="json") if request_model is not None else None
        )
        started_at = perf_counter()
        try:
            response = await self._http_client.request(
                method,
                url,
                headers=headers,
                json=request_json,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            timeout_type = self._timeout_type(exc)
            LOGGER.warning(
                "AI service timeout endpoint=%s timeout_type=%s error_code=%s",
                endpoint,
                timeout_type,
                "downstream_timeout",
            )
            raise AIServiceTimeoutError(
                endpoint=endpoint,
                timeout_type=timeout_type,
            ) from exc
        except httpx.RequestError as exc:
            LOGGER.warning(
                "AI service connection failure endpoint=%s error_code=%s",
                endpoint,
                "downstream_connection_failure",
            )
            raise AIServiceConnectionError(
                "AI service connection failed",
                endpoint=endpoint,
                error_code="downstream_connection_failure",
            ) from exc

        latency_ms = (perf_counter() - started_at) * 1000
        if response.status_code not in expected_statuses:
            self._raise_for_status(
                endpoint=endpoint,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )

        try:
            payload = json.loads(
                response.content,
                parse_constant=self._reject_json_constant,
            )
        except (UnicodeError, ValueError):
            LOGGER.warning(
                "AI service invalid JSON endpoint=%s status=%s "
                "latency_ms=%.3f error_code=%s",
                endpoint,
                response.status_code,
                latency_ms,
                "invalid_response_json",
            )
            raise AIServiceInvalidJSONError(
                "AI service returned invalid JSON",
                endpoint=endpoint,
                error_code="invalid_response_json",
                status_code=response.status_code,
            ) from None

        try:
            validated = response_model.model_validate(payload)
        except ValidationError:
            LOGGER.warning(
                "AI service response validation failed endpoint=%s status=%s "
                "latency_ms=%.3f error_code=%s",
                endpoint,
                response.status_code,
                latency_ms,
                "invalid_response_schema",
            )
            raise AIServiceResponseValidationError(
                "AI service response failed validation",
                endpoint=endpoint,
                error_code="invalid_response_schema",
                status_code=response.status_code,
            ) from None

        model_version = getattr(validated, "model_version", None)
        LOGGER.info(
            "AI service request completed endpoint=%s status=%s "
            "latency_ms=%.3f validation=success model_version=%s",
            endpoint,
            response.status_code,
            latency_ms,
            model_version or "not_applicable",
        )
        return validated, response.status_code

    @staticmethod
    def _reject_json_constant(value: str) -> Any:
        raise ValueError(f"invalid JSON number constant: {value}")

    @staticmethod
    def _timeout_type(exc: httpx.TimeoutException) -> str:
        if isinstance(exc, httpx.ConnectTimeout):
            return "connect"
        if isinstance(exc, httpx.ReadTimeout):
            return "read"
        if isinstance(exc, httpx.WriteTimeout):
            return "write"
        if isinstance(exc, httpx.PoolTimeout):
            return "pool"
        return "unknown"

    @staticmethod
    def _raise_for_status(
        *,
        endpoint: str,
        status_code: int,
        latency_ms: float,
    ) -> None:
        if status_code in {401, 403}:
            error_type: type[AIServiceHTTPError] = AIServiceAuthenticationError
            error_code = "downstream_authentication_failure"
        elif 400 <= status_code < 500:
            error_type = AIServiceClientResponseError
            error_code = "downstream_client_error"
        elif 500 <= status_code < 600:
            error_type = AIServiceServerResponseError
            error_code = "downstream_server_error"
        else:
            error_type = AIServiceHTTPError
            error_code = "unexpected_downstream_status"

        LOGGER.warning(
            "AI service HTTP failure endpoint=%s status=%s latency_ms=%.3f "
            "error_code=%s",
            endpoint,
            status_code,
            latency_ms,
            error_code,
        )
        raise error_type(
            "AI service returned an unsuccessful status",
            endpoint=endpoint,
            error_code=error_code,
            status_code=status_code,
        )


def create_ai_service_client(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AIServiceClient:
    """Factory suitable for later app-lifespan dependency wiring."""

    return AIServiceClient(
        AIServiceClientConfig.from_settings(settings),
        transport=transport,
    )


__all__ = [
    "AIServiceAuthenticationError",
    "AIServiceClient",
    "AIServiceClientConfig",
    "AIServiceClientResponseError",
    "AIServiceConfigurationError",
    "AIServiceConnectionError",
    "AIServiceError",
    "AIServiceHTTPError",
    "AIServiceInvalidJSONError",
    "AIServiceResponseValidationError",
    "AIServiceServerResponseError",
    "AIServiceTimeoutError",
    "BURNOUT_SIGNALS_ENDPOINT",
    "BurnoutSignalLabel",
    "BurnoutSignalResponse",
    "BurnoutSignalState",
    "CoarseEmotionLabel",
    "CoarseEmotionRequest",
    "CoarseEmotionResponse",
    "CoarseEmotionTopPrediction",
    "LivenessResponse",
    "RecoveryReportGenerationRequest",
    "RecoveryReportGenerationResponse",
    "ReadinessResponse",
    "UncertaintyReason",
    "create_ai_service_client",
]
