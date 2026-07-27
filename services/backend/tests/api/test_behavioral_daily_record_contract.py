from __future__ import annotations

import copy

import pytest
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    ValidationError as JsonSchemaValidationError,
)
from pydantic import ValidationError

from app.models.persistence import BehavioralDailyRecord
from app.schemas.behavioral_records import (
    DailyRecordCreate,
    DailyRecordRead,
    DataCoverage,
    DataSource,
)
from app.services.behavioral_record_mapper import (
    to_daily_record_read,
    to_persistence_create,
)
from tests.daily_record_contract import (
    DAILY_RECORD_SCHEMA,
    DAILY_RECORD_VALIDATOR,
    METRIC_FIELDS,
    canonical_daily_record_payload,
    validate_daily_record_response,
)

USER_ID = "contract-user"


def _shared_record(payload: dict[str, object]) -> dict[str, object]:
    return {"user_id": USER_ID, **copy.deepcopy(payload)}


def _payload_with(field: str, value: object) -> dict[str, object]:
    payload = canonical_daily_record_payload()
    payload[field] = value
    return payload


def _assert_rejected_by_both(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DailyRecordCreate.model_validate(payload)
    with pytest.raises(JsonSchemaValidationError):
        DAILY_RECORD_VALIDATOR.validate(_shared_record(payload))


def test_public_dto_fields_and_required_set_match_shared_contract() -> None:
    shared_fields = set(DAILY_RECORD_SCHEMA["properties"])
    shared_required = set(DAILY_RECORD_SCHEMA["required"])

    assert set(DailyRecordCreate.model_fields) == shared_fields - {"user_id"}
    assert {
        name
        for name, field in DailyRecordCreate.model_fields.items()
        if field.is_required()
    } == shared_required - {"user_id"}
    assert set(DailyRecordRead.model_fields) == shared_fields
    assert {
        name
        for name, field in DailyRecordRead.model_fields.items()
        if field.is_required()
    } == shared_required


def test_full_daily_record_read_serialization_validates_against_shared_schema() -> None:
    serialized = DailyRecordRead.model_validate(
        _shared_record(canonical_daily_record_payload())
    ).model_dump(mode="json")

    assert set(serialized) == set(DAILY_RECORD_SCHEMA["properties"])
    validate_daily_record_response(serialized)


def test_public_dto_json_schemas_expose_shared_conditional_all_of() -> None:
    for model in (DailyRecordCreate, DailyRecordRead):
        assert (
            model.model_json_schema()["allOf"]
            == DAILY_RECORD_SCHEMA["allOf"]
        )


def test_field_metadata_enums_exactly_match_shared_contract() -> None:
    assert {item.value for item in DataSource} == set(
        DAILY_RECORD_SCHEMA["$defs"]["dataSource"]["enum"]
    )
    assert {item.value for item in DataCoverage} == set(
        DAILY_RECORD_SCHEMA["$defs"]["dataCoverage"]["enum"]
    )


@pytest.mark.parametrize("metadata_field", ["source_by_field", "coverage_by_field"])
def test_field_metadata_requires_exact_metric_keys(
    metadata_field: str,
) -> None:
    missing = canonical_daily_record_payload()
    del missing[metadata_field]["rest_minutes"]
    _assert_rejected_by_both(missing)

    extra = canonical_daily_record_payload()
    extra[metadata_field]["subjective_stress"] = "manual"
    _assert_rejected_by_both(extra)


@pytest.mark.parametrize(
    ("metadata_field", "invalid_value"),
    [
        ("source_by_field", "calendar"),
        ("coverage_by_field", "unknown"),
    ],
)
def test_field_metadata_rejects_values_outside_shared_enums(
    metadata_field: str,
    invalid_value: str,
) -> None:
    payload = canonical_daily_record_payload()
    payload[metadata_field]["sleep_minutes"] = invalid_value

    _assert_rejected_by_both(payload)


@pytest.mark.parametrize("field", METRIC_FIELDS)
def test_null_value_requires_unavailable_coverage(field: str) -> None:
    payload = canonical_daily_record_payload()
    payload[field] = None

    _assert_rejected_by_both(payload)


@pytest.mark.parametrize("field", METRIC_FIELDS)
def test_unavailable_coverage_requires_null_value(field: str) -> None:
    payload = canonical_daily_record_payload()
    payload["coverage_by_field"][field] = "unavailable"

    _assert_rejected_by_both(payload)


@pytest.mark.parametrize("field", METRIC_FIELDS)
def test_non_null_value_cannot_use_not_provided_source(field: str) -> None:
    payload = canonical_daily_record_payload()
    payload["source_by_field"][field] = "not_provided"

    _assert_rejected_by_both(payload)


def test_null_value_preserves_known_source_and_unavailable_coverage() -> None:
    payload = canonical_daily_record_payload(sleep_minutes=None)
    payload["source_by_field"]["sleep_minutes"] = "health_platform"
    payload["coverage_by_field"]["sleep_minutes"] = "unavailable"

    record = DailyRecordCreate.model_validate(payload)
    DAILY_RECORD_VALIDATOR.validate(_shared_record(payload))

    assert record.sleep_minutes is None
    assert record.source_by_field.sleep_minutes.value == "health_platform"


def test_observed_zero_is_preserved_for_all_numeric_metrics() -> None:
    numeric_fields = (
        "sleep_minutes",
        "steps",
        "active_minutes",
        "exercise_minutes",
        "work_or_study_minutes",
        "rest_minutes",
        "schedule_count",
        "subjective_fatigue",
    )
    payload = canonical_daily_record_payload()
    for field in numeric_fields:
        payload[field] = 0

    record = DailyRecordCreate.model_validate(payload)
    serialized = record.model_dump(mode="json")
    DAILY_RECORD_VALIDATOR.validate(_shared_record(serialized))

    assert all(serialized[field] == 0 for field in numeric_fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("steps", True),
        ("steps", "7420"),
        ("active_minutes", False),
        ("active_minutes", "52"),
        ("subjective_fatigue", True),
        ("subjective_fatigue", "6.0"),
    ],
)
def test_numeric_fields_reject_boolean_and_string_coercion(
    field: str,
    value: object,
) -> None:
    _assert_rejected_by_both(_payload_with(field, value))


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-20T00:00:00",
        "2026-7-20",
        True,
    ],
)
def test_date_requires_exact_json_schema_wire_format(value: object) -> None:
    _assert_rejected_by_both(_payload_with("date", value))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bedtime", "23:40"),
        ("bedtime", "23:40:00.000"),
        ("bedtime", "23:40:00Z"),
        ("wake_time", "24:00:00"),
    ],
)
def test_local_times_require_exact_valid_hh_mm_ss(
    field: str,
    value: str,
) -> None:
    _assert_rejected_by_both(_payload_with(field, value))


@pytest.mark.parametrize("value", ["00:00:00", "23:59:59"])
def test_local_times_accept_whole_second_day_boundaries(value: str) -> None:
    payload = canonical_daily_record_payload(
        bedtime=value,
        wake_time=value,
    )

    record = DailyRecordCreate.model_validate(payload)
    DAILY_RECORD_VALIDATOR.validate(_shared_record(payload))

    assert record.model_dump(mode="json")["bedtime"] == value
    assert record.model_dump(mode="json")["wake_time"] == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("steps", -1),
        ("steps", 1.5),
        ("active_minutes", -1),
        ("active_minutes", 1441),
        ("schedule_count", 1.5),
    ],
)
def test_steps_and_active_minutes_reject_out_of_range_values(
    field: str,
    value: int,
) -> None:
    _assert_rejected_by_both(_payload_with(field, value))


@pytest.mark.parametrize(
    "arbitrary_precision_value",
    [
        0,
        2_147_483_647,
        2_147_483_648,
        9_223_372_036_854_775_807,
        9_223_372_036_854_775_808,
        2**100 + 12345,
    ],
)
def test_steps_and_active_minutes_accept_contract_boundaries(
    arbitrary_precision_value: int,
) -> None:
    payload = canonical_daily_record_payload(
        steps=arbitrary_precision_value,
        active_minutes=1440,
        schedule_count=arbitrary_precision_value,
    )

    record = DailyRecordCreate.model_validate(payload)
    DAILY_RECORD_VALIDATOR.validate(_shared_record(payload))

    assert record.steps == arbitrary_precision_value
    assert record.active_minutes == 1440
    assert record.schedule_count == arbitrary_precision_value


def test_canonical_to_persistence_to_response_round_trip() -> None:
    canonical = canonical_daily_record_payload(
        sleep_minutes=0,
        bedtime=None,
    )
    canonical["source_by_field"]["bedtime"] = "health_platform"
    canonical["coverage_by_field"]["bedtime"] = "unavailable"
    public_create = DailyRecordCreate.model_validate(canonical)

    persistence_create = to_persistence_create(public_create)
    persisted = BehavioralDailyRecord(
        user_id=USER_ID,
        **persistence_create.model_dump(),
    )
    serialized = to_daily_record_read(persisted).model_dump(mode="json")

    assert serialized == _shared_record(canonical)
    validate_daily_record_response(serialized)
    assert persistence_create.record_date == public_create.date
    assert persistence_create.timezone == public_create.time_zone
    assert persistence_create.study_work_minutes == public_create.work_or_study_minutes
    assert set(persistence_create.source_by_field or {}) == set(METRIC_FIELDS)
