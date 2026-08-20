import { apiFetch } from "./client";

export type RecoveryPlanStatus = "planned" | "completed";
export type RecoveryDifficulty = "easy" | "medium";

export interface RecoveryPlanItem {
  id: string;
  user_id: string;
  source_report_id: string | null;
  action_id: string;
  title: string;
  duration_minutes: number | null;
  difficulty: RecoveryDifficulty;
  status: RecoveryPlanStatus;
  selected_at: string;
  completed_at: string | null;
}

export async function getRecoveryPlan(): Promise<RecoveryPlanItem[]> {
  return apiFetch<RecoveryPlanItem[]>("/api/v1/recovery-plans");
}

export async function addRecoveryPlanItem(
  actionId: string,
  sourceReportId?: string,
): Promise<RecoveryPlanItem> {
  return apiFetch<RecoveryPlanItem>("/api/v1/recovery-plans", {
    method: "POST",
    body: JSON.stringify({
      action_id: actionId,
      ...(sourceReportId ? { source_report_id: sourceReportId } : {}),
    }),
  });
}

export async function updateRecoveryPlanItem(
  itemId: string,
  status: RecoveryPlanStatus,
): Promise<RecoveryPlanItem> {
  return apiFetch<RecoveryPlanItem>(`/api/v1/recovery-plans/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

// app/schemas/recovery_plan.py의 RecoveryPlanSettingsResponse와 1:1.
export interface RecoveryPlanSettings {
  notification_time: string | null; // "HH:MM:SS"
  target_period_start: string | null; // YYYY-MM-DD
  target_period_end: string | null; // YYYY-MM-DD
  updated_at: string;
}

// 아직 한 번도 설정한 적 없는 사용자도 항상 200 + null 필드로 받는다
// (서버가 첫 조회 시 빈 행을 만들어 둔다) -- "설정 없음"을 에러로 다루지 않는다.
export async function getRecoveryPlanSettings(): Promise<RecoveryPlanSettings> {
  return apiFetch<RecoveryPlanSettings>("/api/v1/recovery-plans/settings");
}

export interface RecoveryPlanSettingsUpdate {
  notification_time?: string | null; // "HH:MM:SS" — 필드를 아예 안 보내면(undefined) 기존 값을 그대로 둔다
  // 시작일/종료일은 항상 한 쌍으로 같이 보내야 한다(서버가 강제).
  target_period_start?: string | null;
  target_period_end?: string | null;
}

export async function updateRecoveryPlanSettings(
  payload: RecoveryPlanSettingsUpdate,
): Promise<RecoveryPlanSettings> {
  return apiFetch<RecoveryPlanSettings>("/api/v1/recovery-plans/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
