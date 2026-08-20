from __future__ import annotations

import asyncio
import json

import httpx

from app.clients.ai import (
    AIServiceClient,
    AIServiceClientConfig,
    BurnoutSignalLabel,
    BurnoutSignalState,
    CoarseEmotionRequest,
)


def test_burnout_signal_client_uses_separate_informational_endpoint() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["json"] = json.loads(request.content)
        labels = [label.value for label in BurnoutSignalLabel]
        return httpx.Response(
            200,
            request=request,
            json={
                "taxonomy_version": "stage2-burnout-signals-v1",
                "model_version": "synthetic-multilabel-v1",
                "threshold_version": "synthetic-threshold-v1",
                "probabilities": {label: 0.1 for label in labels},
                "thresholds": {label: 1.0 for label in labels},
                "signal_states": {
                    label: BurnoutSignalState.UNVALIDATED.value for label in labels
                },
                "active_signals": [],
                "validated_signals": [],
                "deployment_status": "shadow_only",
                "informational_only": True,
                "risk_score_eligible": False,
                "latency_ms": 1.0,
            },
        )

    async def run() -> object:
        async with AIServiceClient(
            AIServiceClientConfig(
                base_url="https://ai.internal/service/",
                connect_timeout_seconds=1.0,
                read_timeout_seconds=10.0,
                write_timeout_seconds=2.0,
                pool_timeout_seconds=1.0,
            ),
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.analyze_burnout_signals(
                CoarseEmotionRequest(hs01="첫 문장", hs02="둘째 문장")
            )

    result = asyncio.run(run())
    assert result.deployment_status == "shadow_only"
    assert result.risk_score_eligible is False
    assert observed == {
        "url": "https://ai.internal/service/v1/burnout-signals/analyze",
        "json": {"hs01": "첫 문장", "hs02": "둘째 문장", "hs03": None},
    }
