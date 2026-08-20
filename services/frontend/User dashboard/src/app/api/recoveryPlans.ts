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
