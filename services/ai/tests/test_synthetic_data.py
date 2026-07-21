"""합성 생활 데이터와 외부 평가셋 초안의 기본 계약을 검증한다."""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import fmean

from ai.src.schemas import CauseTag, EmotionLabel


AI_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DATA_PATH = AI_ROOT / "data" / "synthetic" / "synthetic_daily_records.csv"
EVALUATION_DATA_PATH = AI_ROOT / "data" / "evaluation" / "remind_diary_eval.csv"

REQUIRED_SYNTHETIC_COLUMNS = {
    "user_id",
    "date",
    "sleep_minutes",
    "steps",
    "active_minutes",
    "exercise_minutes",
    "work_or_study_minutes",
    "rest_minutes",
    "schedule_count",
    "subjective_fatigue",
    "sleep_source",
    "steps_source",
    "coverage",
    "time_zone",
}
NUMERIC_COLUMNS = {
    "sleep_minutes",
    "steps",
    "active_minutes",
    "exercise_minutes",
    "work_or_study_minutes",
    "rest_minutes",
    "schedule_count",
    "subjective_fatigue",
}
INTEGER_COLUMNS = NUMERIC_COLUMNS - {"subjective_fatigue"}
MINUTE_COLUMNS = {
    "sleep_minutes",
    "active_minutes",
    "exercise_minutes",
    "work_or_study_minutes",
    "rest_minutes",
}
EXPECTED_SCENARIOS = {"stable_user", "worsening_user", "insufficient_user"}
EXPECTED_SCENARIO_WINDOWS = {
    "stable_user": (date(2026, 1, 1), date(2026, 1, 14)),
    "worsening_user": (date(2026, 2, 1), date(2026, 2, 21)),
    "insufficient_user": (date(2026, 3, 1), date(2026, 3, 7)),
}
PATTERN_FIELDS = ("sleep_minutes", "steps", "active_minutes", "rest_minutes")
IANA_TIME_ZONE_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9._+-]*"
    r"(?:/[A-Za-z0-9][A-Za-z0-9._+-]*)*$"
)

REQUIRED_EVALUATION_COLUMNS = {
    "id",
    "text",
    "primary_emotion",
    "secondary_signals",
    "cause_tags",
    "review_status",
    "review_note",
}
EXPECTED_EMOTIONS = {label.value for label in EmotionLabel}
EXPECTED_CAUSE_TAGS = {tag.value for tag in CauseTag}
REQUIRED_CONTEXT_PHRASES = {
    "시험",
    "팀 프로젝트",
    "아르바이트",
    "면접",
    "야근",
    "잠이 부족",
    "평범한 하루",
    "회복",
}
REQUIRED_PERSONA_PHRASES = {"대학생", "취업 준비생", "사회초년생"}
SECONDARY_REVIEW_MARKERS = {
    "eval_012": "secondary anxiety 원문 근거 재검토",
    "eval_021": "secondary fatigue 원문 근거 재검토",
}


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        assert reader.fieldnames is not None

        rows: list[dict[str, str]] = []
        for raw_row in reader:
            assert None not in raw_row, f"{path.name} 행에 헤더 밖의 값이 있습니다."
            assert all(value is not None for value in raw_row.values())
            rows.append(
                {
                    str(key): str(value)
                    for key, value in raw_row.items()
                    if key is not None and value is not None
                }
            )
    return list(reader.fieldnames), rows


def _parse_iso_date(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return parsed.isoformat()


def _dates(rows: list[dict[str, str]]) -> list[date]:
    return [datetime.strptime(row["date"], "%Y-%m-%d").date() for row in rows]


def _is_strictly_monotonic(
    values: list[float],
    *,
    decreasing: bool,
) -> bool:
    comparisons = zip(values, values[1:])
    if decreasing:
        return all(earlier > later for earlier, later in comparisons)
    return all(earlier < later for earlier, later in comparisons)


def _scenario_rows(rows: list[dict[str, str]], scenario: str) -> list[dict[str, str]]:
    return sorted(
        (row for row in rows if row["user_id"] == scenario),
        key=lambda row: row["date"],
    )


def _values(rows: list[dict[str, str]], field: str) -> list[float]:
    return [float(row[field]) for row in rows if row[field] != ""]


def test_synthetic_data_has_required_columns_and_rows() -> None:
    fieldnames, rows = _read_csv(SYNTHETIC_DATA_PATH)

    assert REQUIRED_SYNTHETIC_COLUMNS.issubset(fieldnames)
    assert rows
    assert all(set(row) == set(fieldnames) for row in rows)


def test_synthetic_dates_are_iso_and_unique_per_scenario() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)

    scenario_dates = [(row["user_id"], row["date"]) for row in rows]
    assert len(scenario_dates) == len(set(scenario_dates))
    assert all(_parse_iso_date(row["date"]) == row["date"] for row in rows)


def test_scenario_dates_match_documented_contiguous_windows() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)

    for scenario, (expected_start, expected_end) in EXPECTED_SCENARIO_WINDOWS.items():
        scenario_dates = _dates(_scenario_rows(rows, scenario))
        expected_days = (expected_end - expected_start).days + 1

        assert scenario_dates[0] == expected_start
        assert scenario_dates[-1] == expected_end
        assert len(scenario_dates) == expected_days
        assert all(
            later - earlier == timedelta(days=1)
            for earlier, later in zip(scenario_dates, scenario_dates[1:])
        )


def test_synthetic_numeric_values_use_basic_physical_ranges() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)

    for row in rows:
        for field in INTEGER_COLUMNS:
            value = row[field]
            if value == "":
                continue
            parsed = int(value)
            assert str(parsed) == value
            assert parsed >= 0, f"{row['user_id']} {row['date']} {field}"

        for field in MINUTE_COLUMNS:
            value = row[field]
            if value == "":
                continue
            assert int(value) <= 1440, f"{row['user_id']} {row['date']} {field}"

        fatigue = row["subjective_fatigue"]
        if fatigue != "":
            assert 1 <= float(fatigue) <= 5


def test_synthetic_missing_values_are_distinct_from_observed_zero() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)

    assert any(row["sleep_minutes"] == "" for row in rows)
    assert any(row["steps"] == "" for row in rows)
    assert any(row["exercise_minutes"] == "0" for row in rows)

    unavailable_rows = [row for row in rows if row["coverage"] == "unavailable"]
    assert unavailable_rows
    assert all(
        all(row[field] == "" for field in NUMERIC_COLUMNS) for row in unavailable_rows
    )


def test_coverage_matches_fixture_value_availability() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)

    for row in rows:
        values = [row[field] for field in NUMERIC_COLUMNS]
        if row["coverage"] == "complete":
            assert all(value != "" for value in values)
        elif row["coverage"] == "partial":
            assert any(value != "" for value in values)
        else:
            assert row["coverage"] == "unavailable"
            assert all(value == "" for value in values)


def test_all_required_scenarios_exist_with_expected_data_sufficiency() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)

    assert {row["user_id"] for row in rows} == EXPECTED_SCENARIOS

    stable_rows = _scenario_rows(rows, "stable_user")
    worsening_rows = _scenario_rows(rows, "worsening_user")
    insufficient_rows = _scenario_rows(rows, "insufficient_user")

    assert len(stable_rows) == 14
    assert len(worsening_rows) == 21
    assert len(insufficient_rows) == 7
    assert all(row["coverage"] == "complete" for row in stable_rows)
    assert all(row["coverage"] == "complete" for row in worsening_rows)
    assert {row["coverage"] for row in insufficient_rows} == {
        "complete",
        "partial",
        "unavailable",
    }
    assert sum(row["coverage"] == "complete" for row in insufficient_rows) < 14


def test_stable_scenario_fluctuates_without_one_way_decline() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)
    stable_rows = _scenario_rows(rows, "stable_user")

    for field in PATTERN_FIELDS:
        values = _values(stable_rows, field)
        assert len(values) == 14
        assert not _is_strictly_monotonic(values, decreasing=True)
        assert not _is_strictly_monotonic(values, decreasing=False)
        assert any(earlier < later for earlier, later in zip(values, values[1:]))
        assert any(earlier > later for earlier, later in zip(values, values[1:]))


def test_stable_recent_window_stays_within_its_own_early_range() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)
    stable_rows = _scenario_rows(rows, "stable_user")
    early_rows = stable_rows[:7]
    recent_rows = stable_rows[-7:]

    for field in ("sleep_minutes", "steps", "rest_minutes"):
        early_values = _values(early_rows, field)
        recent_values = _values(recent_rows, field)

        assert len(early_values) == 7
        assert len(recent_values) == 7
        assert min(early_values) <= fmean(recent_values) <= max(early_values)

    early_fatigue = _values(early_rows, "subjective_fatigue")
    recent_fatigue = _values(recent_rows, "subjective_fatigue")
    assert fmean(recent_fatigue) <= max(early_fatigue)


def test_worsening_scenario_has_baseline_and_recent_decline() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)
    worsening_rows = _scenario_rows(rows, "worsening_user")

    assert len(worsening_rows) == 21
    baseline_rows = worsening_rows[:14]
    recent_rows = worsening_rows[-7:]

    for field in PATTERN_FIELDS:
        baseline_values = _values(baseline_rows, field)
        recent_values = _values(recent_rows, field)
        assert len(baseline_values) == 14
        assert len(recent_values) == 7
        assert fmean(recent_values) < fmean(baseline_values)
        assert _is_strictly_monotonic(recent_values, decreasing=True)

    recent_fatigue = _values(recent_rows, "subjective_fatigue")
    assert _is_strictly_monotonic(
        recent_fatigue,
        decreasing=False,
    )


def test_synthetic_origin_metadata_contains_no_person_identifier() -> None:
    _, rows = _read_csv(SYNTHETIC_DATA_PATH)

    assert all(row["user_id"] in EXPECTED_SCENARIOS for row in rows)
    assert all(row["sleep_source"] == "synthetic" for row in rows)
    assert all(row["steps_source"] == "synthetic" for row in rows)
    assert all(
        IANA_TIME_ZONE_PATTERN.fullmatch(row["time_zone"]) is not None for row in rows
    )
    assert {row["coverage"] for row in rows} <= {
        "complete",
        "partial",
        "unavailable",
    }


def test_diary_evaluation_draft_has_exactly_30_balanced_rows() -> None:
    fieldnames, rows = _read_csv(EVALUATION_DATA_PATH)

    assert REQUIRED_EVALUATION_COLUMNS.issubset(fieldnames)
    assert len(rows) == 30
    assert len({row["id"] for row in rows}) == 30

    label_counts = Counter(row["primary_emotion"] for row in rows)
    assert set(label_counts) == EXPECTED_EMOTIONS
    assert max(label_counts.values()) - min(label_counts.values()) <= 1


def test_diary_evaluation_draft_requires_review_and_marks_synthetic_origin() -> None:
    _, rows = _read_csv(EVALUATION_DATA_PATH)

    assert all(row["review_status"] == "needs_human_review" for row in rows)
    assert all("합성 문장" in row["review_note"] for row in rows)
    assert all("외부 평가셋 초안" in row["review_note"] for row in rows)
    assert all("학습 사용 전 검토 필요" in row["review_note"] for row in rows)


def test_disputed_secondary_signals_are_explicitly_review_gated() -> None:
    _, rows = _read_csv(EVALUATION_DATA_PATH)
    rows_by_id = {row["id"]: row for row in rows}

    for row_id, marker in SECONDARY_REVIEW_MARKERS.items():
        assert marker in rows_by_id[row_id]["review_note"]
        assert rows_by_id[row_id]["review_status"] == "needs_human_review"


def test_diary_evaluation_draft_covers_required_contexts_and_personas() -> None:
    _, rows = _read_csv(EVALUATION_DATA_PATH)

    texts = "\n".join(row["text"] for row in rows)
    assert all(phrase in texts for phrase in REQUIRED_CONTEXT_PHRASES)
    assert all(phrase in texts for phrase in REQUIRED_PERSONA_PHRASES)

    for row in rows:
        cause_tags = {tag for tag in row["cause_tags"].split("|") if tag}
        assert cause_tags <= EXPECTED_CAUSE_TAGS

        secondary_signals = {
            signal for signal in row["secondary_signals"].split("|") if signal
        }
        assert secondary_signals <= EXPECTED_EMOTIONS
        assert row["primary_emotion"] not in secondary_signals
