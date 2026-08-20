import { apiFetch } from "./client";
import { getCurrentUser, type UserType } from "./users";

// app/models/assessment.py의 AssessmentType / InterpretationScope
export type AssessmentType = "custom_initial_state_survey" | "k_bat";
export type InterpretationScope = "fixed_reference_only";

// app/models/user.py의 UserType — 검사 결과를 어떤 집단 기준으로 볼지 정한다.
// api/users.ts의 UserType과 같은 값이라 그대로 재사용한다.
export type { UserType };

// app/schemas/assessment.py의 DimensionKey와 1:1.
// 앞 4개는 온보딩 초기 상태 설문용, 뒤 3개는 K-BAT 하위영역용이고
// exhaustion(탈진)은 두 검사가 공유한다.
export type DimensionKey =
  | "exhaustion"
  | "academic_burden"
  | "occupational_burden"
  | "recovery_difficulty"
  | "mental_distance"
  | "cognitive_control"
  | "emotional_control";

/** 차원별 점수. 응답하지 않은 차원은 null.
 *  - custom_initial_state_survey의 4개 차원: 0(부담 없음)~1(부담 큼)
 *  - k_bat(BurnoutFlow, source: "onboarding_kbat_v2")의 4개 하위영역:
 *    리커트 원점수 그대로 1(전혀 그렇지 않다)~5(항상 그렇다) 평균값.
 *    자세한 채점 방식은 app/domain/kbat/scoring.py 참고. */
export type DimensionScores = Partial<Record<DimensionKey, number | null>>;

export interface AssessmentAnchorCreate {
  assessment_type: AssessmentType;
  target_group: UserType;
  completed_at: string; // ISO8601, 타임존 필수 -- new Date().toISOString()
  dimensions: DimensionScores;
  source: string;
  supersedes_id?: string | null;
}

export interface AssessmentAnchorRead extends AssessmentAnchorCreate {
  id: string;
  user_id: string;
  interpretation_scope: InterpretationScope;
  created_at: string;
}

const USER_TYPES: readonly UserType[] = ["university_student", "job_seeker", "early_career_worker"];

/** 검사 저장에 필수인 target_group을 알아낸다.
 *  user_type이 아직 비어있거나(온보딩 중 계정) 호출이 실패하면 null --
 *  자가진단 화면이 저장 때문에 막히면 안 되므로 호출부가 저장을 건너뛴다. */
export async function getTargetGroup(): Promise<UserType | null> {
  try {
    const user = await getCurrentUser();
    return USER_TYPES.includes(user.user_type as UserType) ? (user.user_type as UserType) : null;
  } catch {
    return null;
  }
}

export async function createAssessmentAnchor(
  payload: AssessmentAnchorCreate
): Promise<AssessmentAnchorRead> {
  return apiFetch<AssessmentAnchorRead>("/assessments/anchor", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// app/services/kbat_result.py의 KBatResultState와 1:1.
export type KBatResultState = "not_taken" | "insufficient_records" | "ready";

// app/domain/kbat/models.py의 KBatRiskLevel과 1:1.
export type KBatRiskLevel = "good" | "caution" | "warning";

export interface KBatResultScores {
  exhaustion_average: number;
  mental_distance_average: number;
  cognitive_control_average: number;
  emotional_control_average: number;
  total_average: number;
  risk_level: KBatRiskLevel;
}

export interface KBatResultResponse {
  state: KBatResultState;
  recorded_days: number;
  minimum_required_days: number;
  survey_completed_at: string | null;
  result: KBatResultScores | null;
}

// 설문을 아직 안 했거나(not_taken) 일상기록이 최소 일수 미만(insufficient_records)이어도
// 항상 200으로 그 상태를 알려준다 -- "결과 없음"은 오류가 아니라 정상 상태다 (#137/#138과 같은 원칙).
export async function getKBatResult(): Promise<KBatResultResponse> {
  return apiFetch<KBatResultResponse>("/assessments/kbat-result");
}
