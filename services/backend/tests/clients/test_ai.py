from __future__ import annotations

import asyncio
import copy
import json
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, TypeVar

import httpx
import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import SecretStr, ValidationError

from app.clients.ai import (
    AIServiceAuthenticationError,
    AIServiceClient,
    AIServiceClientConfig,
    AIServiceClientResponseError,
    AIServiceConfigurationError,
    AIServiceConnectionError,
    AIServiceInvalidJSONError,
    AIServiceResponseValidationError,
    AIServiceServerResponseError,
    AIServiceTimeoutError,
    CoarseEmotionLabel,
    CoarseEmotionRequest,
    CoarseEmotionResponse,
)

Result = TypeVar("Result")
Handler = Callable[[httpx.Request], httpx.Response]


def run(coroutine: Coroutine[Any, Any, Result]) -> Result:
    return asyncio.run(coroutine)


def client_config(
    *,
    base_url: str = "https://ai.internal/service/",
    auth_token: str | None = None,
) -> AIServiceClientConfig:
    return AIServiceClientConfig(
        base_url=base_url,
        connect_timeout_seconds=1.25,
        read_timeout_seconds=22.5,
        write_timeout_seconds=3.5,
        pool_timeout_seconds=0.75,
        auth_token=SecretStr(auth_token) if auth_token is not None else None,
    )


def request_model() -> CoarseEmotionRequest:
    return CoarseEmotionRequest(
        hs01="합성 첫 문장",
        hs02="합성 두 번째 문장",
        hs03=None,
    )


def valid_response_payload() -> dict[str, Any]:
    return {
        "taxonomy_version": "v2",
        "model_version": "synthetic-coarse-v2",
        "threshold_version": "mvp-v1",
        "predicted_emotion": "불안",
        "predicted_label_id": 2,
        "emotion": "불안",
        "confidence": 0.54,
        "margin": 0.40,
        "provisional": False,
        "is_uncertain": False,
        "uncertainty_reason": None,
        "probabilities": {
            "기쁨": 0.03,
            "불안": 0.54,
            "당황": 0.14,
            "분노": 0.08,
            "슬픔": 0.13,
            "무기력": 0.08,
        },
        "top_predictions": [
            {"emotion": "불안", "label_id": 2, "probability": 0.54},
            {"emotion": "당황", "label_id": 3, "probability": 0.14},
        ],
        "latency_ms": 1.5,
    }


def json_response(
    request: httpx.Request,
    payload: object,
    *,
    status_code: int = 200,
) -> httpx.Response:
    return httpx.Response(status_code, request=request, json=payload)


async def classify_with(handler: Handler) -> CoarseEmotionResponse:
    async with AIServiceClient(
        client_config(),
        transport=httpx.MockTransport(handler),
    ) as client:
        return await client.classify_emotion(request_model())


def test_base_url_endpoint_join_request_serialization_and_timeouts() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["url"] = str(request.url)
        observed["json"] = json.loads(request.content)
        observed["timeout"] = request.extensions["timeout"]
        return json_response(request, valid_response_payload())

    result = run(classify_with(handler))

    assert result.predicted_emotion is CoarseEmotionLabel.ANXIETY
    assert observed == {
        "method": "POST",
        "url": "https://ai.internal/service/v2/emotions/classify",
        "json": {
            "hs01": "합성 첫 문장",
            "hs02": "합성 두 번째 문장",
            "hs03": None,
        },
        "timeout": {
            "connect": 1.25,
            "read": 22.5,
            "write": 3.5,
            "pool": 0.75,
        },
    }


def test_request_normalization_matches_ai_wire_contract() -> None:
    request = CoarseEmotionRequest(
        hs01="  합성   첫 문장 ",
        hs02="합성\n둘째 문장",
        hs03=" \t ",
    )

    assert request.model_dump(mode="json") == {
        "hs01": "합성 첫 문장",
        "hs02": "합성 둘째 문장",
        "hs03": None,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hs01", ""),
        ("hs02", "  "),
        ("hs01", 123),
        ("hs02", "x" * 2001),
    ],
)
def test_invalid_request_is_rejected_before_http(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {"hs01": "first", "hs02": "second"}
    payload[field] = value

    with pytest.raises(ValidationError):
        CoarseEmotionRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("exception_type", "timeout_type"),
    [
        (httpx.ConnectTimeout, "connect"),
        (httpx.ReadTimeout, "read"),
        (httpx.WriteTimeout, "write"),
        (httpx.PoolTimeout, "pool"),
    ],
)
def test_timeout_is_safely_classified(
    exception_type: type[httpx.TimeoutException],
    timeout_type: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("private timeout detail", request=request)

    with pytest.raises(AIServiceTimeoutError) as captured:
        run(classify_with(handler))

    assert captured.value.timeout_type == timeout_type
    assert captured.value.endpoint == "v2/emotions/classify"
    assert isinstance(captured.value.__cause__, exception_type)
    assert "private timeout detail" not in str(captured.value)


def test_connection_failure_preserves_cause_without_private_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private DNS detail", request=request)

    with pytest.raises(AIServiceConnectionError) as captured:
        run(classify_with(handler))

    assert isinstance(captured.value.__cause__, httpx.ConnectError)
    assert captured.value.error_code == "downstream_connection_failure"
    assert "private DNS detail" not in str(captured.value)


@pytest.mark.parametrize("status_code", [400, 422, 429])
def test_downstream_client_errors_are_classified(status_code: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(
            request,
            {"detail": "private request content"},
            status_code=status_code,
        )

    with pytest.raises(AIServiceClientResponseError) as captured:
        run(classify_with(handler))

    assert captured.value.status_code == status_code
    assert captured.value.error_code == "downstream_client_error"
    assert "private request content" not in str(captured.value)
    assert calls == 1


@pytest.mark.parametrize("status_code", [401, 403])
def test_downstream_authentication_errors_are_distinct(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"detail": "denied"}, status_code=status_code)

    with pytest.raises(AIServiceAuthenticationError) as captured:
        run(classify_with(handler))

    assert captured.value.status_code == status_code
    assert captured.value.error_code == "downstream_authentication_failure"


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_downstream_server_errors_are_classified(status_code: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request, {"detail": "failed"}, status_code=status_code)

    with pytest.raises(AIServiceServerResponseError) as captured:
        run(classify_with(handler))

    assert captured.value.status_code == status_code
    assert captured.value.error_code == "downstream_server_error"
    assert calls == 1


@pytest.mark.parametrize(
    "content",
    [
        b"not-json",
        b'{"confidence": NaN}',
        b'{"confidence": Infinity}',
        b"\xff",
    ],
)
def test_invalid_json_and_non_finite_constants_are_rejected(content: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            content=content,
            headers={"content-type": "application/json"},
        )

    with pytest.raises(AIServiceInvalidJSONError) as captured:
        run(classify_with(handler))

    assert captured.value.error_code == "invalid_response_json"


def invalid_response_cases() -> list[tuple[str, dict[str, Any]]]:
    missing_field = valid_response_payload()
    missing_field.pop("model_version")

    wrong_type = valid_response_payload()
    wrong_type["confidence"] = "0.54"

    unknown_class = valid_response_payload()
    unknown_class["probabilities"]["놀람"] = unknown_class["probabilities"].pop(
        "무기력"
    )

    missing_class = valid_response_payload()
    missing_class["probabilities"].pop("무기력")

    out_of_range = valid_response_payload()
    out_of_range["probabilities"]["기쁨"] = 1.1

    bad_sum = valid_response_payload()
    bad_sum["probabilities"]["기쁨"] = 0.04

    extra_field = valid_response_payload()
    extra_field["private_text"] = "must not be accepted"

    wrong_taxonomy = valid_response_payload()
    wrong_taxonomy["taxonomy_version"] = "v1"

    inconsistent_abstention = valid_response_payload()
    inconsistent_abstention["provisional"] = True
    inconsistent_abstention["is_uncertain"] = True
    inconsistent_abstention["uncertainty_reason"] = "small_margin"

    return [
        ("missing field", missing_field),
        ("wrong type", wrong_type),
        ("unknown emotion", unknown_class),
        ("missing emotion", missing_class),
        ("probability out of range", out_of_range),
        ("probabilities do not sum to one", bad_sum),
        ("extra field", extra_field),
        ("wrong taxonomy", wrong_taxonomy),
        ("inconsistent abstention", inconsistent_abstention),
    ]


@pytest.mark.parametrize(
    ("case_name", "payload"),
    invalid_response_cases(),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_invalid_response_schema_is_rejected(
    case_name: str,
    payload: dict[str, Any],
) -> None:
    del case_name

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, payload)

    with pytest.raises(AIServiceResponseValidationError) as captured:
        run(classify_with(handler))

    assert captured.value.error_code == "invalid_response_schema"
    assert captured.value.__cause__ is None


def test_auth_token_and_sensitive_request_are_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "dummy-private-token"
    sensitive_text = "민감한 합성 원문"
    observed_authorization: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_authorization
        observed_authorization = request.headers.get("authorization")
        return json_response(request, valid_response_payload())

    async def scenario() -> None:
        client = AIServiceClient(
            client_config(auth_token=token),
            transport=httpx.MockTransport(handler),
        )
        async with client:
            await client.classify_emotion(
                CoarseEmotionRequest(
                    hs01=sensitive_text,
                    hs02="두 번째 합성 문장",
                )
            )

    with caplog.at_level(logging.INFO, logger="app.clients.ai"):
        run(scenario())

    assert observed_authorization == f"Bearer {token}"
    assert "v2/emotions/classify" in caplog.text
    assert "validation=success" in caplog.text
    assert sensitive_text not in caplog.text
    assert token not in caplog.text
    assert token not in repr(client_config(auth_token=token))


def test_injected_http_client_remains_owned_by_caller() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, valid_response_payload())

    async def scenario() -> tuple[bool, bool]:
        external = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = AIServiceClient(client_config(), http_client=external)
        await client.classify_emotion(request_model())
        await client.aclose()
        states = (client.is_closed, external.is_closed)
        await external.aclose()
        return states

    assert run(scenario()) == (True, False)


def test_owned_client_context_closes_and_close_is_idempotent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, valid_response_payload())

    async def scenario() -> tuple[bool, bool]:
        client = AIServiceClient(
            client_config(),
            transport=httpx.MockTransport(handler),
        )
        async with client:
            await client.classify_emotion(request_model())
            open_state = client.is_closed
        await client.aclose()
        return open_state, client.is_closed

    assert run(scenario()) == (False, True)


def test_closed_client_fails_without_network_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request, valid_response_payload())

    async def scenario() -> None:
        client = AIServiceClient(
            client_config(),
            transport=httpx.MockTransport(handler),
        )
        await client.aclose()
        await client.classify_emotion(request_model())

    with pytest.raises(AIServiceConfigurationError, match="closed"):
        run(scenario())
    assert calls == 0


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "ai.internal",
        "ftp://ai.internal",
        "https://user:secret@ai.internal",
        "https://ai.internal?token=private",
        "https://ai.internal/#fragment",
    ],
)
def test_invalid_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(AIServiceConfigurationError) as captured:
        AIServiceClient(client_config(base_url=base_url))

    assert captured.value.error_code == "invalid_base_url"


@pytest.mark.parametrize("value", [0, -1, 301, float("nan"), float("inf")])
def test_invalid_constructor_timeout_is_rejected(value: float) -> None:
    with pytest.raises(AIServiceConfigurationError) as captured:
        AIServiceClientConfig(
            base_url="https://ai.internal",
            connect_timeout_seconds=value,
            read_timeout_seconds=20,
            write_timeout_seconds=5,
            pool_timeout_seconds=1,
        )

    assert captured.value.error_code == "invalid_timeout"


def test_http_client_and_transport_cannot_both_be_injected() -> None:
    async_client = httpx.AsyncClient()
    try:
        with pytest.raises(AIServiceConfigurationError) as captured:
            AIServiceClient(
                client_config(),
                http_client=async_client,
                transport=httpx.MockTransport(
                    lambda request: json_response(
                        request,
                        valid_response_payload(),
                    )
                ),
            )
    finally:
        run(async_client.aclose())

    assert captured.value.error_code == "conflicting_http_dependencies"


def test_health_endpoints_distinguish_liveness_and_model_readiness() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        if request.url.path.endswith("/health/live"):
            return json_response(request, {"status": "ok"})
        return json_response(
            request,
            {"status": "not_ready"},
            status_code=503,
        )

    async def scenario() -> tuple[str, bool]:
        async with AIServiceClient(
            client_config(),
            transport=httpx.MockTransport(handler),
        ) as client:
            live = await client.check_liveness()
            ready = await client.check_readiness()
            return live.status, ready.is_ready

    assert run(scenario()) == ("ok", False)
    assert observed_paths == [
        "/service/health/live",
        "/service/health/ready",
    ]


@pytest.mark.parametrize(
    ("status_code", "payload"),
    [
        (200, {"status": "not_ready"}),
        (503, {"status": "ready"}),
        (200, {"status": "unknown"}),
    ],
)
def test_readiness_http_status_and_payload_must_agree(
    status_code: int,
    payload: dict[str, str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, payload, status_code=status_code)

    async def scenario() -> None:
        async with AIServiceClient(
            client_config(),
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.check_readiness()

    with pytest.raises(AIServiceResponseValidationError):
        run(scenario())


def test_backend_models_validate_shared_ai_json_contracts() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    schemas = repository_root / "packages" / "contracts" / "schemas"
    request_schema = json.loads(
        (
            schemas / "remind_coarse_emotion_inference_request.schema.json"
        ).read_text(
            encoding="utf-8"
        )
    )
    response_schema = json.loads(
        (
            schemas / "remind_coarse_emotion_inference_response.schema.json"
        ).read_text(
            encoding="utf-8"
        )
    )
    request_payload = request_model().model_dump(mode="json")
    response_payload = valid_response_payload()

    Draft202012Validator(request_schema).validate(request_payload)
    Draft202012Validator(response_schema).validate(response_payload)
    assert CoarseEmotionRequest.model_validate(request_payload)
    assert CoarseEmotionResponse.model_validate(copy.deepcopy(response_payload))
