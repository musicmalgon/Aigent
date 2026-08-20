import { apiFetch } from "./client";
import type { ReportFactorCode, ReportGenerationStatus, RiskLevel } from "./recoveryReports";

// app/schemas/dashboard.py 기준
export type BaselineStatus = "ready" | "insufficient" | "missing";

// 리포트에 실리는 코드와 달리 대시보드는 "판단 불가" 코드도 그대로 내려준다
// (app/domain/risk/models.py의 FactorCode 전체)
export type DashboardFactorCode = ReportFactorCode | "insufficient_baseline" | "insufficient_data";

// app/services/dashboard.py의 ReadinessState -- 홈 화면 빈 상태 사다리
export type ReadinessState =
  | "insufficient_records"
  | "baseline_pending"
  | "baseline_ready"
  | "risk_evaluation_ready"
  | "recovery_report_ready";

export interface DashboardRecordStatus {
  today_recorded: boolean;
  recorded_days: number;
}

export interface DashboardBaselineStatus {
  status: BaselineStatus;
  sample_days: number;
  window_end: string; // YYYY-MM-DD
  created_at: string;
}

export interface DashboardRiskStatus {
  level: RiskLevel;
  date: string; // YYYY-MM-DD
  top_factors: DashboardFactorCode[]; // 기여도 내림차순, 최대 3개
}

export interface DashboardReportStatus {
  id: string;
  headline: string;
  generation_status: ReportGenerationStatus;
  generated_at: string;
}

export interface DashboardResponse {
  record_status: DashboardRecordStatus;
  baseline: DashboardBaselineStatus | null;
  latest_risk: DashboardRiskStatus | null;
  latest_report: DashboardReportStatus | null;
}

export interface ReadinessResponse {
  state: ReadinessState;
}

export async function getDashboard(): Promise<DashboardResponse> {
  return apiFetch<DashboardResponse>("/api/v1/dashboard");
}

export async function getReadiness(): Promise<ReadinessResponse> {
  return apiFetch<ReadinessResponse>("/api/v1/readiness");
}
