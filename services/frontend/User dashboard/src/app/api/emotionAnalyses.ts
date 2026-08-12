import { apiFetch } from "./client";

// app/clients/ai.py의 CoarseEmotionLabel 기준
export type CoarseEmotionLabel = "분노" | "기쁨" | "불안" | "당황" | "슬픔" | "무기력";

export interface EmotionAnalysisCreate {
  record_date: string; // YYYY-MM-DD. 같은 날짜의 behavioral-record가 먼저 있어야 함 (없으면 404)
  hs01: string; // 필수, 1~2000자
  hs02: string; // 필수, 1~2000자
  hs03?: string | null; // 선택, 1~2000자
}

export interface EmotionAnalysisRead {
  id: string;
  user_id: string;
  record_date: string;
  analyzed_at: string;
  taxonomy_version: string; // 예: "v2" — 정확한 enum은 schemas/persistence.py 확인 필요
  model_version: string;
  predicted_emotion: CoarseEmotionLabel | null;
  emotion: CoarseEmotionLabel | null;
  confidence: number | null; // 0~1
  margin: number | null; // 0~1
  provisional: boolean;
  is_uncertain: boolean;
  probabilities: Partial<Record<CoarseEmotionLabel, number>> | null;
  threshold_version: string | null;
  neutral_gate_decision: "neutral" | "emotional" | null;
  neutral_gate_score: number | null;
  neutral_gate_model_version: string | null;
  neutral_gate_threshold: number | null;
  created_at: string;
}

/** record_date에 해당하는 behavioral-record가 먼저 저장돼 있어야 함 (없으면 404).
 *  emotion_diary consent가 GRANTED 상태여야 함 (없으면 403). */
export async function createEmotionAnalysis(
  payload: EmotionAnalysisCreate
): Promise<EmotionAnalysisRead> {
  return apiFetch<EmotionAnalysisRead>("/api/v1/emotion-analyses", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getEmotionAnalyses(): Promise<EmotionAnalysisRead[]> {
  return apiFetch<EmotionAnalysisRead[]>("/api/v1/emotion-analyses");
}

export async function getLatestEmotionAnalysis(): Promise<EmotionAnalysisRead> {
  return apiFetch<EmotionAnalysisRead>("/api/v1/emotion-analyses/latest");
}

export async function getEmotionAnalysisById(resultId: string): Promise<EmotionAnalysisRead> {
  return apiFetch<EmotionAnalysisRead>(`/api/v1/emotion-analyses/${resultId}`);
}