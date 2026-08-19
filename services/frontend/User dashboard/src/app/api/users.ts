import { apiFetch } from "./client";

export interface UserRead {
  id: string;
  email: string;
  name: string;
  user_type?: string;
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