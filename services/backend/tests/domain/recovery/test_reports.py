import asyncio
from datetime import date

import pytest

from app.domain.recovery.catalog import select_recovery_actions
from app.domain.recovery.models import (
    RecoveryActionId,
    RecoveryReportChange,
    RecoveryReportGenerationRequest,
    RecoveryReportPeriod,
    ReportFactorCode,
    ReportMetric,
)
from app.services.recovery_reports import (
    PreparedRecoveryReport,
    build_template_fallback,
    select_recovery_actions_for_report,
)


def request() -> RecoveryReportGenerationRequest:
    factors = [
        ReportFactorCode.SLEEP_DECREASE,
        ReportFactorCode.REST_DECREASE,
    ]
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
                factor_code=ReportFactorCode.SLEEP_DECREASE,
                metric=ReportMetric.SLEEP_MINUTES,
                recent_value=300,
                baseline_value=420,
                delta=-120,
                change_percent=-28.57,
                sample_days=7,
                fact_text=(
                    "최근 7일 중 7일 평균 수면 시간은 300분이고 "
                    "평소 기준은 420분입니다."
                ),
            ),
            RecoveryReportChange(
                factor_code=ReportFactorCode.REST_DECREASE,
                metric=ReportMetric.REST_MINUTES,
                recent_value=30,
                baseline_value=90,
                delta=-60,
                change_percent=-66.67,
                sample_days=7,
                fact_text=(
                    "최근 7일 중 7일 평균 휴식 시간은 30분이고 "
                    "평소 기준은 90분입니다."
                ),
            ),
        ],
        selected_actions=select_recovery_actions(factors),
    )


def test_catalog_selection_is_deterministic_and_deduplicated() -> None:
    actions = select_recovery_actions(
        [
            ReportFactorCode.WORKLOAD_INCREASE,
            ReportFactorCode.SCHEDULE_OVERLOAD,
            ReportFactorCode.REST_DECREASE,
        ]
    )

    assert [action.id for action in actions] == [
        RecoveryActionId.SCHEDULE_REDUCE_ONE,
        RecoveryActionId.REST_30,
        RecoveryActionId.LIGHT_ACTIVITY_20,
    ]
    assert [action.id for action in select_recovery_actions([])] == [
        RecoveryActionId.REST_30,
        RecoveryActionId.LIGHT_ACTIVITY_20,
        RecoveryActionId.ROUTINE_CHECK_5,
    ]


def test_stage2_signal_drivers_prioritize_matching_actions() -> None:
    actions = select_recovery_actions(
        [ReportFactorCode.SLEEP_DECREASE],
        stage2_signals=["overload"],
    )

    assert [action.id for action in actions] == [
        RecoveryActionId.SCHEDULE_REDUCE_ONE,
        RecoveryActionId.REST_30,
        RecoveryActionId.SLEEP_EARLY_60,
    ]


class _SelectionClient:
    def __init__(self, ids: list[str] | None = None, error: Exception | None = None):
        self.ids = ids
        self.error = error

    async def select_recovery_actions(self, request: object) -> object:
        del request
        if self.error is not None:
            raise self.error
        return type("Selection", (), {"ids": self.ids or []})()


def _prepared(
    *,
    provisional: bool = False,
    data_quality: str = "sufficient",
) -> PreparedRecoveryReport:
    payload = request().model_copy(
        update={"is_provisional": provisional, "data_quality": data_quality}
    )
    return PreparedRecoveryReport(
        user_id="user-1",
        risk_evaluation_id="evaluation-1",
        request=payload,
        input_snapshot="stable-source-snapshot",
    )


def test_missing_or_insufficient_report_uses_default_candidates() -> None:
    prepared = asyncio.run(select_recovery_actions_for_report(
        _prepared(provisional=True),
        ai_client=_SelectionClient(error=AssertionError("must not call LLM")),
    ))
    assert [item.id for item in prepared.request.selected_actions] == [
        RecoveryActionId.REST_30,
        RecoveryActionId.LIGHT_ACTIVITY_20,
        RecoveryActionId.ROUTINE_CHECK_5,
    ]


def test_valid_llm_selection_is_mapped_in_order() -> None:
    prepared = asyncio.run(select_recovery_actions_for_report(
        _prepared(),
        ai_client=_SelectionClient(
            ids=["sleep_prep_routine", "rest_30min", "step_away_5min"]
        ),
    ))
    assert [item.id for item in prepared.request.selected_actions] == [
        RecoveryActionId.SLEEP_EARLY_60,
        RecoveryActionId.REST_30,
        RecoveryActionId.STEP_AWAY_5,
    ]


@pytest.mark.parametrize(
    "ids",
    [["not_in_pool"], ["rest_30min"] * 4, []],
)
def test_invalid_llm_selection_uses_default_fallback(ids: list[str]) -> None:
    prepared = asyncio.run(select_recovery_actions_for_report(
        _prepared(),
        ai_client=_SelectionClient(ids=ids),
    ))
    assert len(prepared.request.selected_actions) == 3
    assert prepared.request.selected_actions[0].id is RecoveryActionId.SLEEP_EARLY_60


def test_llm_timeout_or_error_uses_default_fallback() -> None:
    prepared = asyncio.run(select_recovery_actions_for_report(
        _prepared(),
        ai_client=_SelectionClient(error=TimeoutError("selection timed out")),
    ))
    assert len(prepared.request.selected_actions) == 3
    assert prepared.request.selected_actions[0].id is RecoveryActionId.SLEEP_EARLY_60


def test_template_fallback_preserves_factors_and_action_ids() -> None:
    payload = request()
    result = build_template_fallback(payload)

    assert [item.factor_code for item in result.changed_items] == [
        item.factor_code for item in payload.changes
    ]
    assert [
        item.action_id for item in result.recommendation_descriptions
    ] == [action.id for action in payload.selected_actions]
    assert "진단" not in result.headline
    assert "7일" in result.weekly_observation


def test_report_change_rejects_inconsistent_numeric_group() -> None:
    with pytest.raises(ValueError):
        RecoveryReportChange(
            factor_code=ReportFactorCode.SLEEP_DECREASE,
            metric=ReportMetric.SLEEP_MINUTES,
            recent_value=None,
            baseline_value=420,
            delta=-120,
            change_percent=-28.57,
            sample_days=7,
            fact_text="합성 설명",
        )
