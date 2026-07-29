from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.assessment import AssessmentAnchor
from app.models.user import User
from app.schemas.assessment import AssessmentAnchorCreate, AssessmentAnchorRead

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