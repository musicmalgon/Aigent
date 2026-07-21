"""Contract tests for the Re:Mind AI foundation schemas.

All examples loaded by this module are synthetic examples embedded in the
repository's JSON Schema documents.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ValidationError

from ai.src.schemas import (
    AssessmentAnchor,
    BaselineMetric,
    BehavioralBaseline,
    BehavioralDailyRecord,
    BehavioralMetric,
    CombinedResultType,
    CombinedSignalResult,
    EmotionAnalysis,
    MetricSufficiency,
    PatternChangeResult,
)


SCHEMA_DIR = Path(__file__).parents[3] / "packages" / "contracts" / "schemas"
MODEL_BY_SCHEMA: dict[str, type[BaseModel]] = {
    "assessment_anchor.schema.json": AssessmentAnchor,
    "behavioral_daily_record.schema.json": BehavioralDailyRecord,
    "behavioral_baseline.schema.json": BehavioralBaseline,
    "emotion_analysis.schema.json": EmotionAnalysis,
    "pattern_change.schema.json": PatternChangeResult,
    "combined_signal_result.schema.json": CombinedSignalResult,
}


def _load_schema(filename: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))


def _first_example(filename: str) -> dict[str, Any]:
    schema = _load_schema(filename)
    return copy.deepcopy(schema["examples"][0])


def _assert_rejected_by_both(
    filename: str,
    model: type[BaseModel],
    payload: dict[str, Any],
) -> None:
    """Require the public JSON and Python contracts to reject one payload."""

    validator = Draft202012Validator(
        _load_schema(filename),
        format_checker=FormatChecker(),
    )
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(payload)
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("filename", "model"),
    MODEL_BY_SCHEMA.items(),
)
def test_each_model_accepts_its_valid_example(
    filename: str,
    model: type[BaseModel],
) -> None:
    instance = model.model_validate(_first_example(filename))
    assert isinstance(instance, model)


@pytest.mark.parametrize(
    ("filename", "model"),
    MODEL_BY_SCHEMA.items(),
)
def test_json_schema_examples_match_model_fields_and_validate(
    filename: str,
    model: type[BaseModel],
) -> None:
    """Validate each document and example with JSON Schema and Pydantic."""

    schema = _load_schema(filename)

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["examples"]
    assert "합성" in schema["$comment"]
    assert set(schema["properties"]) == set(model.model_fields)
    assert set(schema["required"]) == set(model.model_fields)

    for example in schema["examples"]:
        validator.validate(example)
        model.model_validate(example)


INVALID_ENUM_CASES = [
    (
        "assessment_anchor.schema.json",
        AssessmentAnchor,
        ("assessment_type",),
        "diagnostic_assessment",
    ),
    (
        "behavioral_daily_record.schema.json",
        BehavioralDailyRecord,
        ("coverage_by_field", "sleep_minutes"),
        "unknown",
    ),
    (
        "behavioral_baseline.schema.json",
        BehavioralBaseline,
        ("data_sufficiency",),
        "maybe",
    ),
    (
        "emotion_analysis.schema.json",
        EmotionAnalysis,
        ("primary_emotion",),
        "burnout",
    ),
    (
        "pattern_change.schema.json",
        PatternChangeResult,
        ("change_level",),
        "diagnosed",
    ),
    (
        "combined_signal_result.schema.json",
        CombinedSignalResult,
        ("combined_level",),
        "high_risk_probability",
    ),
]


@pytest.mark.parametrize(
    ("filename", "model", "path", "invalid_value"),
    INVALID_ENUM_CASES,
)
def test_invalid_enum_values_are_rejected(
    filename: str,
    model: type[BaseModel],
    path: tuple[str, ...],
    invalid_value: str,
) -> None:
    payload = _first_example(filename)
    target: dict[str, Any] = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = invalid_value

    _assert_rejected_by_both(filename, model, payload)


def test_daily_record_distinguishes_zero_from_unavailable() -> None:
    zero_payload = _first_example("behavioral_daily_record.schema.json")
    zero_payload["sleep_minutes"] = 0
    zero_payload["source_by_field"]["sleep_minutes"] = "synthetic"
    zero_payload["coverage_by_field"]["sleep_minutes"] = "complete"

    missing_payload = copy.deepcopy(zero_payload)
    missing_payload["sleep_minutes"] = None
    missing_payload["source_by_field"]["sleep_minutes"] = "not_provided"
    missing_payload["coverage_by_field"]["sleep_minutes"] = "unavailable"

    zero_record = BehavioralDailyRecord.model_validate(zero_payload)
    missing_record = BehavioralDailyRecord.model_validate(missing_payload)
    validator = Draft202012Validator(
        _load_schema("behavioral_daily_record.schema.json"),
        format_checker=FormatChecker(),
    )
    validator.validate(zero_payload)
    validator.validate(missing_payload)

    assert zero_record.sleep_minutes == 0
    assert zero_record.sleep_minutes is not None
    assert missing_record.sleep_minutes is None


@pytest.mark.parametrize(
    ("value", "coverage"),
    [
        (None, "complete"),
        (0, "unavailable"),
    ],
)
def test_daily_record_rejects_value_coverage_mismatch(
    value: int | None,
    coverage: str,
) -> None:
    payload = _first_example("behavioral_daily_record.schema.json")
    payload["sleep_minutes"] = value
    payload["coverage_by_field"]["sleep_minutes"] = coverage

    _assert_rejected_by_both(
        "behavioral_daily_record.schema.json",
        BehavioralDailyRecord,
        payload,
    )


def test_daily_record_requires_metadata_for_every_nullable_field() -> None:
    payload = _first_example("behavioral_daily_record.schema.json")
    del payload["source_by_field"]["rest_minutes"]
    del payload["coverage_by_field"]["rest_minutes"]

    with pytest.raises(ValidationError):
        BehavioralDailyRecord.model_validate(payload)


def test_daily_record_json_schema_requires_all_field_metadata() -> None:
    schema = _load_schema("behavioral_daily_record.schema.json")
    expected_fields = {metric.value for metric in BehavioralMetric}

    for metadata_field in ("source_by_field", "coverage_by_field"):
        metadata_schema = schema["properties"][metadata_field]
        assert metadata_schema["additionalProperties"] is False
        assert set(metadata_schema["properties"]) == expected_fields
        assert set(metadata_schema["required"]) == expected_fields


def test_assessment_dimensions_preserve_zero_and_null() -> None:
    anchor = AssessmentAnchor.model_validate(
        _first_example("assessment_anchor.schema.json")
    )

    assert anchor.dimensions["exhaustion"] == 0
    assert anchor.dimensions["exhaustion"] is not None
    assert anchor.dimensions["recovery_difficulty"] is None


def test_assessment_completed_at_requires_timezone() -> None:
    aware_payload = _first_example("assessment_anchor.schema.json")
    aware_anchor = AssessmentAnchor.model_validate(aware_payload)
    assert aware_anchor.completed_at.utcoffset() is not None

    naive_payload = copy.deepcopy(aware_payload)
    naive_payload["completed_at"] = "2026-01-01T09:00:00"

    with pytest.raises(ValidationError):
        AssessmentAnchor.model_validate(naive_payload)

    schema = _load_schema("assessment_anchor.schema.json")
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(naive_payload)


def _semantic_invalid_cases() -> list[tuple[str, str, type[BaseModel], dict[str, Any]]]:
    cases: list[tuple[str, str, type[BaseModel], dict[str, Any]]] = []

    for case_id, filename, model, field_name in [
        (
            "assessment-whitespace-source",
            "assessment_anchor.schema.json",
            AssessmentAnchor,
            "source",
        ),
        (
            "daily-whitespace-user-id",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            "user_id",
        ),
        (
            "baseline-whitespace-calculation-version",
            "behavioral_baseline.schema.json",
            BehavioralBaseline,
            "calculation_version",
        ),
        (
            "pattern-whitespace-calculation-version",
            "pattern_change.schema.json",
            PatternChangeResult,
            "calculation_version",
        ),
        (
            "combined-whitespace-rule-version",
            "combined_signal_result.schema.json",
            CombinedSignalResult,
            "rule_version",
        ),
    ]:
        whitespace_payload = _first_example(filename)
        whitespace_payload[field_name] = "   "
        cases.append((case_id, filename, model, whitespace_payload))

    daily_null_complete = _first_example("behavioral_daily_record.schema.json")
    daily_null_complete["sleep_minutes"] = None
    cases.append(
        (
            "daily-null-with-complete-coverage",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            daily_null_complete,
        )
    )

    daily_zero_unavailable = _first_example("behavioral_daily_record.schema.json")
    daily_zero_unavailable["sleep_minutes"] = 0
    daily_zero_unavailable["coverage_by_field"]["sleep_minutes"] = "unavailable"
    cases.append(
        (
            "daily-zero-with-unavailable-coverage",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            daily_zero_unavailable,
        )
    )

    daily_value_not_provided = _first_example("behavioral_daily_record.schema.json")
    daily_value_not_provided["source_by_field"]["sleep_minutes"] = "not_provided"
    cases.append(
        (
            "daily-value-with-not-provided-source",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            daily_value_not_provided,
        )
    )

    daily_boolean_steps = _first_example("behavioral_daily_record.schema.json")
    daily_boolean_steps["steps"] = True
    cases.append(
        (
            "daily-boolean-steps",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            daily_boolean_steps,
        )
    )

    daily_string_steps = _first_example("behavioral_daily_record.schema.json")
    daily_string_steps["steps"] = "7420"
    cases.append(
        (
            "daily-string-steps",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            daily_string_steps,
        )
    )

    daily_short_time = _first_example("behavioral_daily_record.schema.json")
    daily_short_time["bedtime"] = "23:40"
    cases.append(
        (
            "daily-time-without-seconds",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            daily_short_time,
        )
    )

    daily_invalid_time_zone = _first_example("behavioral_daily_record.schema.json")
    daily_invalid_time_zone["time_zone"] = "Asia Seoul"
    cases.append(
        (
            "daily-invalid-time-zone",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            daily_invalid_time_zone,
        )
    )

    daily_padded_time_zone = _first_example("behavioral_daily_record.schema.json")
    daily_padded_time_zone["time_zone"] = "Asia/Seoul\n"
    cases.append(
        (
            "daily-padded-time-zone",
            "behavioral_daily_record.schema.json",
            BehavioralDailyRecord,
            daily_padded_time_zone,
        )
    )

    baseline_sufficient_zero = _first_example("behavioral_baseline.schema.json")
    baseline_sufficient_zero["valid_days"] = 0
    cases.append(
        (
            "baseline-sufficient-with-zero-valid-days",
            "behavioral_baseline.schema.json",
            BehavioralBaseline,
            baseline_sufficient_zero,
        )
    )

    baseline_string_valid_days = _first_example("behavioral_baseline.schema.json")
    baseline_string_valid_days["valid_days"] = "14"
    cases.append(
        (
            "baseline-string-valid-days",
            "behavioral_baseline.schema.json",
            BehavioralBaseline,
            baseline_string_valid_days,
        )
    )

    baseline_unavailable_metric_with_days = _first_example(
        "behavioral_baseline.schema.json"
    )
    baseline_unavailable_metric_with_days["sufficiency_by_metric"]["steps"] = (
        "unavailable"
    )
    baseline_unavailable_metric_with_days["valid_days_by_metric"]["steps"] = 3
    cases.append(
        (
            "baseline-unavailable-metric-with-valid-days",
            "behavioral_baseline.schema.json",
            BehavioralBaseline,
            baseline_unavailable_metric_with_days,
        )
    )

    baseline_partial_metric_without_days = _first_example(
        "behavioral_baseline.schema.json"
    )
    baseline_partial_metric_without_days["valid_days_by_metric"]["rest_minutes"] = 0
    cases.append(
        (
            "baseline-partial-metric-with-zero-valid-days",
            "behavioral_baseline.schema.json",
            BehavioralBaseline,
            baseline_partial_metric_without_days,
        )
    )

    baseline_mismatched_metric_keys = _first_example("behavioral_baseline.schema.json")
    del baseline_mismatched_metric_keys["sufficiency_by_metric"]["steps"]
    cases.append(
        (
            "baseline-mismatched-metric-keys",
            "behavioral_baseline.schema.json",
            BehavioralBaseline,
            baseline_mismatched_metric_keys,
        )
    )

    baseline_summary_without_metadata = _first_example(
        "behavioral_baseline.schema.json"
    )
    baseline_summary_without_metadata["averages"]["active_minutes"] = 30
    cases.append(
        (
            "baseline-summary-without-valid-day-metadata",
            "behavioral_baseline.schema.json",
            BehavioralBaseline,
            baseline_summary_without_metadata,
        )
    )

    baseline_zero_days_with_summary = _first_example("behavioral_baseline.schema.json")
    baseline_zero_days_with_summary["valid_days_by_metric"]["steps"] = 0
    baseline_zero_days_with_summary["sufficiency_by_metric"]["steps"] = "insufficient"
    cases.append(
        (
            "baseline-zero-valid-days-with-numeric-summary",
            "behavioral_baseline.schema.json",
            BehavioralBaseline,
            baseline_zero_days_with_summary,
        )
    )

    duplicate_secondary = _first_example("emotion_analysis.schema.json")
    duplicate_secondary["secondary_signals"] = ["anxiety", "anxiety"]
    cases.append(
        (
            "emotion-duplicate-secondary",
            "emotion_analysis.schema.json",
            EmotionAnalysis,
            duplicate_secondary,
        )
    )

    primary_repeated_as_secondary = _first_example("emotion_analysis.schema.json")
    primary_repeated_as_secondary["secondary_signals"] = [
        primary_repeated_as_secondary["primary_emotion"]
    ]
    cases.append(
        (
            "emotion-primary-repeated-as-secondary",
            "emotion_analysis.schema.json",
            EmotionAnalysis,
            primary_repeated_as_secondary,
        )
    )

    emotion_coerced_boolean = _first_example("emotion_analysis.schema.json")
    emotion_coerced_boolean["sleep_related"] = 0
    cases.append(
        (
            "emotion-numeric-boolean",
            "emotion_analysis.schema.json",
            EmotionAnalysis,
            emotion_coerced_boolean,
        )
    )

    emotion_string_confidence = _first_example("emotion_analysis.schema.json")
    emotion_string_confidence["confidence"] = "0.72"
    cases.append(
        (
            "emotion-string-confidence",
            "emotion_analysis.schema.json",
            EmotionAnalysis,
            emotion_string_confidence,
        )
    )

    emotion_whitespace_model_name = _first_example("emotion_analysis.schema.json")
    emotion_whitespace_model_name["model_name"] = "   "
    cases.append(
        (
            "emotion-whitespace-model-name",
            "emotion_analysis.schema.json",
            EmotionAnalysis,
            emotion_whitespace_model_name,
        )
    )

    pattern_insufficient_observed = _first_example("pattern_change.schema.json")
    pattern_insufficient_observed["data_sufficiency"] = "insufficient"
    cases.append(
        (
            "pattern-insufficient-with-observed-change",
            "pattern_change.schema.json",
            PatternChangeResult,
            pattern_insufficient_observed,
        )
    )

    pattern_unavailable_with_duration = _first_example("pattern_change.schema.json")
    pattern_unavailable_with_duration.update(
        {
            "data_sufficiency": "unavailable",
            "change_level": "unknown",
            "duration_days": 2,
            "factors": [],
        }
    )
    cases.append(
        (
            "pattern-unavailable-with-positive-duration",
            "pattern_change.schema.json",
            PatternChangeResult,
            pattern_unavailable_with_duration,
        )
    )

    pattern_insufficient_with_factors = _first_example("pattern_change.schema.json")
    pattern_insufficient_with_factors.update(
        {
            "data_sufficiency": "insufficient",
            "change_level": "unknown",
            "duration_days": None,
        }
    )
    cases.append(
        (
            "pattern-insufficient-with-factors",
            "pattern_change.schema.json",
            PatternChangeResult,
            pattern_insufficient_with_factors,
        )
    )

    pattern_observed_without_factors = _first_example("pattern_change.schema.json")
    pattern_observed_without_factors["factors"] = []
    cases.append(
        (
            "pattern-observed-without-factors",
            "pattern_change.schema.json",
            PatternChangeResult,
            pattern_observed_without_factors,
        )
    )

    pattern_observed_without_duration = _first_example("pattern_change.schema.json")
    pattern_observed_without_duration["duration_days"] = None
    cases.append(
        (
            "pattern-observed-without-duration",
            "pattern_change.schema.json",
            PatternChangeResult,
            pattern_observed_without_duration,
        )
    )

    pattern_stable_with_positive_duration = _first_example("pattern_change.schema.json")
    pattern_stable_with_positive_duration.update(
        {
            "change_level": "no_notable_change",
            "duration_days": 1,
            "factors": [],
        }
    )
    cases.append(
        (
            "pattern-no-change-with-positive-duration",
            "pattern_change.schema.json",
            PatternChangeResult,
            pattern_stable_with_positive_duration,
        )
    )

    pattern_string_change_amount = _first_example("pattern_change.schema.json")
    pattern_string_change_amount["factors"][0]["change_amount"] = "45"
    cases.append(
        (
            "pattern-string-change-amount",
            "pattern_change.schema.json",
            PatternChangeResult,
            pattern_string_change_amount,
        )
    )

    combined_stable_with_missing_health = _first_example(
        "combined_signal_result.schema.json"
    )
    combined_stable_with_missing_health.update(
        {
            "result_type": "health_data_not_connected",
            "missing_signals": ["health", "behavior"],
        }
    )
    cases.append(
        (
            "combined-stable-with-missing-health",
            "combined_signal_result.schema.json",
            CombinedSignalResult,
            combined_stable_with_missing_health,
        )
    )

    combined_change_with_stable_result = _first_example(
        "combined_signal_result.schema.json"
    )
    combined_change_with_stable_result["combined_level"] = "change_detected"
    cases.append(
        (
            "combined-change-with-all-stable-result",
            "combined_signal_result.schema.json",
            CombinedSignalResult,
            combined_change_with_stable_result,
        )
    )

    combined_stable_with_reason = _first_example("combined_signal_result.schema.json")
    combined_stable_with_reason["reason_codes"] = ["HEALTH_DATA_NOT_CONNECTED"]
    cases.append(
        (
            "combined-all-stable-with-reason",
            "combined_signal_result.schema.json",
            CombinedSignalResult,
            combined_stable_with_reason,
        )
    )

    combined_contract_cases: list[tuple[str, dict[str, Any]]] = [
        (
            "combined-assessment-result-without-required-reasons",
            {
                "combined_level": "indeterminate",
                "result_type": "assessment_elevated_without_recent_change",
            },
        ),
        (
            "combined-recent-result-with-wrong-level",
            {
                "combined_level": "indeterminate",
                "result_type": "recent_change_without_assessment_elevation",
            },
        ),
        (
            "combined-aligned-result-without-alignment-reason",
            {
                "combined_level": "change_detected",
                "result_type": "multiple_signals_aligned",
            },
        ),
        (
            "combined-present-result-with-alignment-reason",
            {
                "combined_level": "change_detected",
                "result_type": "multiple_signals_present",
                "reason_codes": ["MULTIPLE_SIGNALS_ALIGNED"],
            },
        ),
        (
            "combined-insufficient-result-without-missing-evidence",
            {
                "combined_level": "indeterminate",
                "result_type": "behavior_data_insufficient",
            },
        ),
        (
            "combined-health-result-without-missing-evidence",
            {
                "combined_level": "indeterminate",
                "result_type": "health_data_not_connected",
            },
        ),
        (
            "combined-emotion-result-without-missing-evidence",
            {
                "combined_level": "indeterminate",
                "result_type": "emotion_data_missing",
            },
        ),
    ]
    for case_id, updates in combined_contract_cases:
        payload = _first_example("combined_signal_result.schema.json")
        payload.update(updates)
        cases.append(
            (
                case_id,
                "combined_signal_result.schema.json",
                CombinedSignalResult,
                payload,
            )
        )

    return cases


@pytest.mark.parametrize(
    ("case_id", "filename", "model", "payload"),
    _semantic_invalid_cases(),
    ids=[case[0] for case in _semantic_invalid_cases()],
)
def test_semantic_invalid_payloads_are_rejected_by_both_contracts(
    case_id: str,
    filename: str,
    model: type[BaseModel],
    payload: dict[str, Any],
) -> None:
    del case_id
    _assert_rejected_by_both(filename, model, payload)


@pytest.mark.parametrize(
    ("case_id", "updates"),
    [
        (
            "all-stable",
            {},
        ),
        (
            "assessment-elevated",
            {
                "combined_level": "indeterminate",
                "result_type": "assessment_elevated_without_recent_change",
                "reason_codes": [
                    "ASSESSMENT_EXHAUSTION_ELEVATED",
                    "SELF_REPORT_ELEVATED_WITHOUT_RECENT_CHANGE",
                ],
                "top_factors": ["assessment.exhaustion"],
            },
        ),
        (
            "recent-change",
            {
                "combined_level": "change_detected",
                "result_type": "recent_change_without_assessment_elevation",
                "reason_codes": ["SLEEP_DECREASE_CONTINUED"],
                "top_factors": ["sleep_minutes"],
            },
        ),
        (
            "multiple-aligned",
            {
                "combined_level": "change_detected",
                "result_type": "multiple_signals_aligned",
                "reason_codes": [
                    "SLEEP_DECREASE_CONTINUED",
                    "FATIGUE_EXPRESSION_REPEATED",
                    "MULTIPLE_SIGNALS_ALIGNED",
                ],
                "top_factors": ["sleep_minutes", "emotion.fatigue"],
            },
        ),
        (
            "multiple-present",
            {
                "combined_level": "change_detected",
                "result_type": "multiple_signals_present",
                "reason_codes": [
                    "SLEEP_DECREASE_CONTINUED",
                    "FATIGUE_EXPRESSION_REPEATED",
                ],
                "top_factors": ["sleep_minutes", "emotion.fatigue"],
            },
        ),
        (
            "behavior-insufficient",
            {
                "combined_level": "indeterminate",
                "result_type": "behavior_data_insufficient",
                "reason_codes": ["BEHAVIOR_DATA_INSUFFICIENT"],
                "missing_signals": ["behavior"],
            },
        ),
        (
            "health-not-connected",
            {
                "combined_level": "indeterminate",
                "result_type": "health_data_not_connected",
                "reason_codes": ["HEALTH_DATA_NOT_CONNECTED"],
                "missing_signals": ["health", "behavior"],
            },
        ),
        (
            "emotion-missing",
            {
                "combined_level": "indeterminate",
                "result_type": "emotion_data_missing",
                "reason_codes": ["EMOTION_DATA_MISSING"],
                "missing_signals": ["emotion"],
            },
        ),
    ],
)
def test_combined_result_types_accept_matching_contracts(
    case_id: str,
    updates: dict[str, Any],
) -> None:
    del case_id
    filename = "combined_signal_result.schema.json"
    payload = _first_example(filename)
    payload.update(updates)

    Draft202012Validator(
        _load_schema(filename),
        format_checker=FormatChecker(),
    ).validate(payload)
    CombinedSignalResult.model_validate(payload)


def test_pattern_unknown_state_is_valid_only_for_unusable_data() -> None:
    payload = _first_example("pattern_change.schema.json")
    payload.update(
        {
            "data_sufficiency": "insufficient",
            "change_level": "unknown",
            "duration_days": None,
            "factors": [],
        }
    )

    Draft202012Validator(
        _load_schema("pattern_change.schema.json"),
        format_checker=FormatChecker(),
    ).validate(payload)
    result = PatternChangeResult.model_validate(payload)
    assert result.duration_days is None
    assert result.factors == []


def test_pattern_no_notable_change_uses_zero_duration() -> None:
    payload = _first_example("pattern_change.schema.json")
    payload.update(
        {
            "change_level": "no_notable_change",
            "duration_days": 0,
            "factors": [],
        }
    )

    Draft202012Validator(
        _load_schema("pattern_change.schema.json"),
        format_checker=FormatChecker(),
    ).validate(payload)
    result = PatternChangeResult.model_validate(payload)
    assert result.duration_days == 0
    assert result.factors == []


def test_baseline_metric_keys_are_restricted_to_enum_values() -> None:
    payload = _first_example("behavioral_baseline.schema.json")
    payload["valid_days_by_metric"]["free_form_metric"] = 1
    payload["sufficiency_by_metric"]["free_form_metric"] = "partial"

    _assert_rejected_by_both(
        "behavioral_baseline.schema.json",
        BehavioralBaseline,
        payload,
    )
    assert {metric.value for metric in BaselineMetric} == {
        "sleep_minutes",
        "steps",
        "active_minutes",
        "exercise_minutes",
        "work_or_study_minutes",
        "rest_minutes",
        "schedule_count",
        "subjective_fatigue",
    }


def test_changed_json_enums_match_pydantic_enums() -> None:
    baseline_schema = _load_schema("behavioral_baseline.schema.json")
    pattern_schema = _load_schema("pattern_change.schema.json")
    combined_schema = _load_schema("combined_signal_result.schema.json")

    baseline_metric_values = {metric.value for metric in BaselineMetric}
    assert (
        set(baseline_schema["$defs"]["baselineMetric"]["enum"])
        == baseline_metric_values
    )
    assert (
        set(pattern_schema["$defs"]["behavioralMetric"]["enum"])
        == baseline_metric_values
    )
    assert set(baseline_schema["$defs"]["metricSufficiency"]["enum"]) == {
        state.value for state in MetricSufficiency
    }
    assert set(combined_schema["$defs"]["combinedResultType"]["enum"]) == {
        result_type.value for result_type in CombinedResultType
    }


@pytest.mark.parametrize("metric", list(BaselineMetric))
def test_baseline_metric_metadata_rules_match_for_every_metric(
    metric: BaselineMetric,
) -> None:
    filename = "behavioral_baseline.schema.json"
    validator = Draft202012Validator(
        _load_schema(filename),
        format_checker=FormatChecker(),
    )

    valid_unavailable = _first_example(filename)
    valid_unavailable["valid_days_by_metric"][metric.value] = 0
    valid_unavailable["sufficiency_by_metric"][metric.value] = "unavailable"
    for summary_field in (
        "averages",
        "medians",
        "weekday_averages",
        "weekend_averages",
    ):
        valid_unavailable[summary_field][metric.value] = None
    validator.validate(valid_unavailable)
    BehavioralBaseline.model_validate(valid_unavailable)

    unavailable_with_days = copy.deepcopy(valid_unavailable)
    unavailable_with_days["valid_days_by_metric"][metric.value] = 1
    _assert_rejected_by_both(
        filename,
        BehavioralBaseline,
        unavailable_with_days,
    )

    partial_without_days = copy.deepcopy(valid_unavailable)
    partial_without_days["sufficiency_by_metric"][metric.value] = "partial"
    _assert_rejected_by_both(
        filename,
        BehavioralBaseline,
        partial_without_days,
    )

    missing_sufficiency = copy.deepcopy(valid_unavailable)
    del missing_sufficiency["sufficiency_by_metric"][metric.value]
    _assert_rejected_by_both(
        filename,
        BehavioralBaseline,
        missing_sufficiency,
    )


def test_baseline_dynamic_day_comparisons_are_enforced_by_pydantic() -> None:
    """Draft 2020-12 cannot compare two instance numbers dynamically."""

    payload = _first_example("behavioral_baseline.schema.json")
    payload["valid_days_by_metric"]["steps"] = payload["valid_days"] + 1

    with pytest.raises(ValidationError, match="overall valid_days"):
        BehavioralBaseline.model_validate(payload)


def test_emotion_relation_null_is_distinct_from_evaluated_false() -> None:
    payload = _first_example("emotion_analysis.schema.json")
    assert payload["sleep_related"] is None
    assert payload["workload_related"] is None

    not_evaluated = EmotionAnalysis.model_validate(payload)
    evaluated_payload = copy.deepcopy(payload)
    evaluated_payload["sleep_related"] = False
    evaluated_payload["workload_related"] = False
    evaluated = EmotionAnalysis.model_validate(evaluated_payload)
    validator = Draft202012Validator(
        _load_schema("emotion_analysis.schema.json"),
        format_checker=FormatChecker(),
    )
    validator.validate(payload)
    validator.validate(evaluated_payload)

    assert not_evaluated.sleep_related is None
    assert not_evaluated.workload_related is None
    assert evaluated.sleep_related is False
    assert evaluated.workload_related is False


def test_daily_record_requires_reproducible_time_zone() -> None:
    filename = "behavioral_daily_record.schema.json"
    payload = _first_example(filename)
    assert payload["time_zone"] == "Asia/Seoul"

    missing_time_zone = copy.deepcopy(payload)
    del missing_time_zone["time_zone"]
    _assert_rejected_by_both(
        filename,
        BehavioralDailyRecord,
        missing_time_zone,
    )
