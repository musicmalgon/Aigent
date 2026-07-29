from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.validators import validator_for  # type: ignore[import-untyped]

from app.domain.risk import (
    BurnoutRiskEngine,
    BurnoutRiskEvaluationRequest,
    BurnoutRiskEvaluationResponse,
    CurrentRiskSignals,
    EmotionProbabilities,
    PersonalBaseline,
)

ROOT = Path(__file__).resolve().parents[5]
SCHEMA_DIR = ROOT / "packages" / "contracts" / "schemas"
REQUEST_PATH = SCHEMA_DIR / "burnout_risk_evaluation_request.schema.json"
RESPONSE_PATH = SCHEMA_DIR / "burnout_risk_evaluation_response.schema.json"


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_contract_schemas_and_examples_remain_valid() -> None:
    paths = sorted(SCHEMA_DIR.glob("*.schema.json"))

    assert len(paths) == 11
    for path in paths:
        schema = load_schema(path)
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        validator = validator_class(schema)
        for example in schema.get("examples", []):
            validator.validate(example)


def test_request_contract_example_matches_pydantic() -> None:
    schema = load_schema(REQUEST_PATH)
    example = schema["examples"][0]

    Draft202012Validator(schema).validate(example)
    model = BurnoutRiskEvaluationRequest.model_validate(example)
    Draft202012Validator(schema).validate(
        model.model_dump(mode="json", by_alias=True)
    )


def test_request_without_optional_emotion_metadata_matches_contract() -> None:
    schema = load_schema(REQUEST_PATH)
    request = BurnoutRiskEvaluationRequest(
        current=CurrentRiskSignals(
            emotion_probabilities=EmotionProbabilities(
                **{
                    "기쁨": 0.5,
                    "불안": 0.1,
                    "당황": 0.1,
                    "분노": 0.1,
                    "슬픔": 0.1,
                    "상처": 0.1,
                }
            )
        )
    )

    Draft202012Validator(schema).validate(
        request.model_dump(mode="json", by_alias=True)
    )


def test_response_contract_example_matches_pydantic() -> None:
    schema = load_schema(RESPONSE_PATH)
    example = schema["examples"][0]

    Draft202012Validator(schema).validate(example)
    BurnoutRiskEvaluationResponse.model_validate(example)


def test_engine_response_validates_against_response_contract() -> None:
    current = CurrentRiskSignals(
        sleep_minutes=270,
        work_or_study_minutes=540,
        rest_minutes=20,
        exercise_minutes=0,
        schedule_count=6,
        subjective_stress=8,
        subjective_fatigue=7,
        emotion_probabilities=EmotionProbabilities(
            **{
                "기쁨": 0.03,
                "불안": 0.42,
                "당황": 0.11,
                "분노": 0.08,
                "슬픔": 0.25,
                "상처": 0.11,
            }
        ),
        emotion_confidence=0.42,
        emotion_uncertain=True,
    )
    baseline = PersonalBaseline(
        sleep_minutes=420,
        work_or_study_minutes=300,
        rest_minutes=90,
        exercise_minutes=25,
        schedule_count=3,
        subjective_stress=4,
        subjective_fatigue=3,
        negative_emotion_probability=0.38,
        sample_days=18,
    )
    result = BurnoutRiskEngine().evaluate(current=current, baseline=baseline)

    Draft202012Validator(load_schema(RESPONSE_PATH)).validate(
        result.model_dump(mode="json")
    )


def test_pydantic_and_json_schema_top_level_shapes_match() -> None:
    request_contract = load_schema(REQUEST_PATH)
    response_contract = load_schema(RESPONSE_PATH)
    request_model = BurnoutRiskEvaluationRequest.model_json_schema(by_alias=True)
    response_model = BurnoutRiskEvaluationResponse.model_json_schema(by_alias=True)

    assert set(request_contract["properties"]) == set(request_model["properties"])
    assert set(request_contract["required"]) == set(request_model["required"])
    assert set(response_contract["properties"]) == set(response_model["properties"])
    assert set(response_contract["required"]) == set(response_model["required"])

    current_contract = request_contract["$defs"]["currentRiskSignals"]
    current_model = request_model["$defs"]["CurrentRiskSignals"]
    baseline_contract = request_contract["$defs"]["personalBaseline"]
    baseline_model = request_model["$defs"]["PersonalBaseline"]
    assert set(current_contract["properties"]) == set(current_model["properties"])
    assert set(baseline_contract["properties"]) == set(baseline_model["properties"])
    assert set(baseline_contract["required"]) == set(baseline_model["required"])


def test_contract_enum_values_match_pydantic_schema() -> None:
    response_contract = load_schema(RESPONSE_PATH)
    response_model = BurnoutRiskEvaluationResponse.model_json_schema()

    pairs = {
        "riskLevel": "RiskLevel",
        "baselineStatus": "BaselineStatus",
        "dataQuality": "DataQuality",
        "factorCategory": "FactorCategory",
        "factorKind": "FactorKind",
        "factorCode": "FactorCode",
    }
    for contract_name, model_name in pairs.items():
        assert set(response_contract["$defs"][contract_name]["enum"]) == set(
            response_model["$defs"][model_name]["enum"]
        )


def test_risk_domain_has_no_framework_or_io_imports() -> None:
    risk_dir = ROOT / "services" / "backend" / "app" / "domain" / "risk"
    forbidden = {
        "fastapi",
        "sqlalchemy",
        "requests",
        "httpx",
        "socket",
        "app.core",
        "backend.app.core",
    }
    imported: set[str] = set()

    for path in risk_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not {
        name
        for name in imported
        if any(name == item or name.startswith(f"{item}.") for item in forbidden)
    }


def test_contract_names_are_unambiguous_and_no_api_was_added() -> None:
    assert REQUEST_PATH.is_file()
    assert RESPONSE_PATH.is_file()
    assert not (SCHEMA_DIR / "burnout_risk_request.schema.json").exists()
    assert not (SCHEMA_DIR / "burnout_risk_response.schema.json").exists()
    assert not (
        ROOT / "services" / "backend" / "app" / "api" / "risks.py"
    ).exists()
