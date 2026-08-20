import { apiFetch } from "./client";

export interface RiskEvaluationResponse {
  id: string;
  user_id: string;
  date: string;
  result: {
    score: number;
    level: "low" | "moderate" | "high" | "very_high";
    is_provisional: boolean;
  };
}

export async function createRiskEvaluation(
  date: string,
): Promise<RiskEvaluationResponse> {
  return apiFetch<RiskEvaluationResponse>("/api/v1/risk-evaluations", {
    method: "POST",
    body: JSON.stringify({ date }),
  });
}
