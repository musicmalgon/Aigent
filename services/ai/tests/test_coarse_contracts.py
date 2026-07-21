"""Focused validation for the six-class shared inference contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai.src.schemas import (
    CoarseEmotionInferenceResponse,
    CoarseEmotionInput,
    CoarseEmotionLabel,
)


SCHEMA_DIR = Path(__file__).parents[3] / "packages" / "contracts" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _response_payload() -> dict[str, object]:
    return copy.deepcopy(
        _schema("coarse_emotion_inference_response.schema.json")["examples"][0]
    )


def test_coarse_request_normalizes_training_turn_inputs() -> None:
    request = CoarseEmotionInput(
        hs01="  요즘   잠을 못 자. ",
        hs02="계속\n불안해.",
        hs03="   ",
    )
    assert request.hs01 == "요즘 잠을 못 자."
    assert request.hs02 == "계속 불안해."
    assert request.hs03 is None


@pytest.mark.parametrize(
    "payload",
    [
        {"hs01": " ", "hs02": "유효한 문장"},
        {"hs01": "유효한 문장", "hs02": ""},
        {"hs01": "가" * 2001, "hs02": "유효한 문장"},
    ],
)
def test_coarse_request_rejects_empty_or_oversized_input(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CoarseEmotionInput.model_validate(payload)


def test_coarse_response_validates_probability_and_ranking_invariants() -> None:
    payload = _response_payload()
    response = CoarseEmotionInferenceResponse.model_validate(payload)
    assert len(response.probabilities) == 6
    assert sum(response.probabilities.values()) == pytest.approx(1.0)
    assert response.predicted_emotion is CoarseEmotionLabel.ANXIETY
    assert response.top_predictions[0].emotion is response.predicted_emotion

    invalid_sum = copy.deepcopy(payload)
    invalid_sum["probabilities"]["기쁨"] = 0.13
    with pytest.raises(ValidationError, match="sum to one"):
        CoarseEmotionInferenceResponse.model_validate(invalid_sum)

    invalid_ranking = copy.deepcopy(payload)
    invalid_ranking["top_predictions"].reverse()
    with pytest.raises(ValidationError, match="sorted"):
        CoarseEmotionInferenceResponse.model_validate(invalid_ranking)


def test_shared_json_contracts_reject_extra_fields_and_invalid_labels() -> None:
    request_schema = _schema("coarse_emotion_inference_request.schema.json")
    response_schema = _schema("coarse_emotion_inference_response.schema.json")
    Draft202012Validator.check_schema(request_schema)
    Draft202012Validator.check_schema(response_schema)

    request = copy.deepcopy(request_schema["examples"][0])
    request["raw_text_log"] = True
    assert not Draft202012Validator(request_schema).is_valid(request)

    response = _response_payload()
    response["predicted_emotion"] = "stable"
    assert not Draft202012Validator(response_schema).is_valid(response)


def test_shared_response_contract_enforces_expressible_cross_field_rules() -> None:
    validator = Draft202012Validator(
        _schema("coarse_emotion_inference_response.schema.json")
    )

    wrong_id = _response_payload()
    wrong_id["predicted_label_id"] = 5
    assert not validator.is_valid(wrong_id)

    wrong_top_id = _response_payload()
    wrong_top_id["top_predictions"][0]["label_id"] = 5
    assert not validator.is_valid(wrong_top_id)

    missing_reason = _response_payload()
    missing_reason["is_uncertain"] = True
    assert not validator.is_valid(missing_reason)
