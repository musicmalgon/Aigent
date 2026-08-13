import { apiFetch } from "./client";

// app/schemas/dashboard.py 전체를 못 봐서 baseline 세부 필드는 넓게 잡아둠
export interface DashboardRecordStatus {
  today_recorded: boolean;
  recorded_days: number;
}

export interface DashboardBaselineStatus {
  [key: string]: unknown; // TODO: schemas/dashboard.py 확인 필요
}

export interface DashboardRiskStatus {
  level: string;
  date: string;
  top_factors: string[];
}

export interface DashboardReportStatus {
  id: string;
  headline: string;
  generation_status: string;
  generated_at: string;
}

export interface DashboardResponse {
  record_status: DashboardRecordStatus;
  baseline: DashboardBaselineStatus | null;
  latest_risk: DashboardRiskStatus | null;
  latest_report: DashboardReportStatus | null;
}

export type ReadinessState = string; // TODO: classify_readiness 반환값 확인 필요

export interface ReadinessResponse {
  state: ReadinessState;
}

export async function getDashboard(): Promise<DashboardResponse> {
  return apiFetch<DashboardResponse>("/api/v1/dashboard");
}

export async function getReadiness(): Promise<ReadinessResponse> {
  return apiFetch<ReadinessResponse>("/api/v1/readiness");
}