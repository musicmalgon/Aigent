import { apiFetch, ApiError } from "./client";

export type RiskLevel = "low" | "moderate" | "high" | "very_high";
export type DataQuality = "sufficient" | "insufficient";
export type ReportGenerationStatus = "llm_generated" | "template_fallback";

export type ReportFactorCode =
  | "sleep_decrease"
  | "workload_increase"
  | "schedule_overload"
  | "rest_decrease"
  | "exercise_decrease"
  | "negative_emotion_increase"
  | "high_negative_emotion"
  | "subjective_stress"
  | "subjective_fatigue";

export type ReportMetric =
  | "sleep_minutes"
  | "work_or_study_minutes"
  | "rest_minutes"
  | "exercise_minutes"
  | "schedule_count"
  | "negative_emotion_probability"
  | "subjective_stress"
  | "subjective_fatigue";

export type RecoveryActionId =
  | "REST_30"
  | "SLEEP_EARLY_60"
  | "LIGHT_ACTIVITY_20"
  | "SCHEDULE_REDUCE_ONE"
  | "JOURNAL_CHECKIN_10"
  | "ROUTINE_CHECK_5";

export type RecoveryDifficulty = "easy" | "medium";

export interface RecoveryReportPeriod {
  start: string; // YYYY-MM-DD
  end: string;
  record_days: number; // 0~7
}

export interface RecoveryReportChange {
  factor_code: ReportFactorCode;
  metric: ReportMetric | null;
  recent_value: number | null;
  baseline_value: number | null;
  delta: number | null;
  change_percent: number | null;
  sample_days: number; // 0~7
  fact_text: string;
}

export interface RecoveryAction {
  id: RecoveryActionId;
  title: string;
  duration_minutes: number | null;
  difficulty: RecoveryDifficulty;
}

export interface RecoveryChangedItem {
  factor_code: ReportFactorCode;
  title: string;
  description: string;
}

export interface RecoveryRecommendationDescription {
  action_id: RecoveryActionId;
  reason: string;
}

export interface RecoveryReportCopy {
  headline: string;
  summary: string;
  weekly_observation: string;
  changed_items: RecoveryChangedItem[]; // 최대 3개
  recommendation_intro: string;
  recommendation_descriptions: RecoveryRecommendationDescription[]; // 1~3개
}

export interface RecoveryReportFacts {
  risk_level: RiskLevel;
  risk_score: number; // 0~100
  is_provisional: boolean;
  data_quality: DataQuality;
  period: RecoveryReportPeriod;
  changes: RecoveryReportChange[]; // 최대 3개
}

export interface RecoveryReportResponse {
  id: string;
  user_id: string;
  risk_evaluation_id: string;
  period_start: string;
  period_end: string;
  facts: RecoveryReportFacts;
  selected_actions: RecoveryAction[]; // 1~3개
  content: RecoveryReportCopy;
  disclaimer: string;
  generation_status: ReportGenerationStatus;
  catalog_version: string;
  prompt_version: string;
  model_name: string | null;
  generated_at: string;
  created_at: string;
}

// 아직 리포트가 생성되기 전(기록이 부족한 경우 등)이면 백엔드가 404를 정상
// 응답으로 준다 -- 에러가 아니라 "없음"이므로 null로 돌려서 화면(ReportView)이
// 이미 갖고 있는 "아직 생성된 리포트가 없어요" 안내로 자연스럽게 이어지게 한다.
export async function getLatestRecoveryReport(): Promise<RecoveryReportResponse | null> {
  try {
    return await apiFetch<RecoveryReportResponse>("/api/v1/recovery-reports/latest");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function getRecoveryReportHistory(params?: {
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
}): Promise<RecoveryReportResponse[]> {
  const search = new URLSearchParams();
  if (params?.dateFrom) search.set("date_from", params.dateFrom);
  if (params?.dateTo) search.set("date_to", params.dateTo);
  if (params?.limit) search.set("limit", String(params.limit));
  if (params?.offset) search.set("offset", String(params.offset));
  const query = search.toString();
  return apiFetch<RecoveryReportResponse[]>(
    `/api/v1/recovery-reports${query ? `?${query}` : ""}`
  );
}