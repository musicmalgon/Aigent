import { apiFetch } from "./client";

// app/models/user.py의 UserType과 1:1. api/assessments.ts의 UserType과 같은 값이다.
export type UserType = "university_student" | "job_seeker" | "early_career_worker";

export interface UserRead {
  id: string;
  email: string;
  name: string;
  user_type?: UserType | null;
}

export async function getCurrentUser(): Promise<UserRead> {
  return apiFetch<UserRead>("/users/me");
}

export async function updateUserName(name: string): Promise<UserRead> {
  return apiFetch<UserRead>("/users/me/name", {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

// 온보딩(Mode 화면)에서 한 번 물어보고 저장한다 -- 검사 앵커 저장(createAssessmentAnchor)이
// target_group을 필수로 요구하므로, 이 값이 없으면 설문 결과가 저장되지 않는다.
export async function updateUserType(userType: UserType): Promise<UserRead> {
  return apiFetch<UserRead>("/users/me/type", {
    method: "PATCH",
    body: JSON.stringify({ user_type: userType }),
  });
}

export async function updateUserPassword(
  currentPassword: string,
  newPassword: string
): Promise<void> {
  await apiFetch<null>("/users/me/password", {
    method: "PATCH",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export interface AccountDataDeletionSummary {
  recovery_plan_items_deleted: number;
  recovery_reports_deleted: number;
  risk_evaluations_deleted: number;
  baselines_deleted: number;
  emotion_analyses_deleted: number;
  daily_records_deleted: number;
  consent_records_deleted: number;
  assessment_anchors_deleted: number;
}

// 되돌릴 수 없는 삭제 — 비밀번호 재확인 필요
export async function deleteAccountData(
  currentPassword: string
): Promise<AccountDataDeletionSummary> {
  return apiFetch<AccountDataDeletionSummary>("/users/me/data", {
    method: "DELETE",
    body: JSON.stringify({ current_password: currentPassword }),
  });
}
