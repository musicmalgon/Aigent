from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.assessment import AssessmentAnchor
from app.models.user import User
from app.schemas.assessment import AssessmentAnchorCreate, AssessmentAnchorRead
from app.schemas.kbat_result import KBatResultResponse
from app.services.kbat_result import gather_kbat_result

router = APIRouter()


@router.post("/assessments/anchor", response_model=AssessmentAnchorRead, status_code=201)
def create_assessment_anchor(
    payload: AssessmentAnchorCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentAnchor:
    anchor = AssessmentAnchor(
        user_id=current_user.id,
        assessment_type=payload.assessment_type,
        target_group=payload.target_group,
        completed_at=payload.completed_at,
        dimensions=payload.dimensions,
        interpretation_scope=payload.interpretation_scope,
        source=payload.source,
        supersedes_id=payload.supersedes_id,
    )
    db.add(anchor)
    db.commit()
    db.refresh(anchor)
    return anchor


@router.get("/assessments/anchor", response_model=AssessmentAnchorRead)
def read_latest_assessment_anchor(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentAnchor:
    latest = (
        db.query(AssessmentAnchor)
        .filter(AssessmentAnchor.user_id == current_user.id)
        .order_by(AssessmentAnchor.created_at.desc())
        .first()
    )
    if latest is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="저장된 검사 응답이 없습니다")
    return latest


@router.get("/assessments/kbat-result", response_model=KBatResultResponse)
def read_kbat_result(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KBatResultResponse:
    """K-BAT 자가진단(설문) + 누적 일상기록을 합친 최종 결과.

    설문을 아직 안 했거나(NOT_TAKEN) 일상기록이 7일 미만(INSUFFICIENT_
    RECORDS)이면 항상 200으로 그 상태를 알려준다 -- "결과가 아직 없음"은
    오류가 아니라 정상 상태이므로 404로 표현하지 않는다(#137/#138과 같은
    원칙).
    """
    snapshot = gather_kbat_result(db, user_id=current_user.id)
    return KBatResultResponse(
        state=snapshot.state,
        recorded_days=snapshot.recorded_days,
        minimum_required_days=snapshot.minimum_required_days,
        survey_completed_at=snapshot.survey_completed_at,
        result=snapshot.result,
    )