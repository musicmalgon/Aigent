import { apiFetch } from "./client";
import { getCurrentUser } from "./users";

// app/models/assessment.py의 AssessmentType / InterpretationScope
export type AssessmentType = "custom_initial_state_survey" | "k_bat";
export type InterpretationScope = "fixed_reference_only";

// app/models/user.py의 UserType — 검사 결과를 어떤 집단 기준으로 볼지 정한다
export type UserType = "university_student" | "job_seeker" | "early_career_worker";

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

/** 차원별 0(부담 없음)~1(부담 큼) 점수. 응답하지 않은 차원은 null. */
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
