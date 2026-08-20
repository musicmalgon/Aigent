import { apiFetch, ApiError } from "./client";

// app/models/persistence.py의 PersistenceBaselineStatus와 1:1.
export type BaselineStatus = "ready" | "insufficient";

// app/schemas/persistence.py의 BaselineRead와 1:1.
export interface BaselineRead {
  id: string;
  user_id: string;
  window_start: string; // YYYY-MM-DD
  window_end: string; // YYYY-MM-DD
  sample_days: number;
  sleep_minutes: number | null;
  study_work_minutes: number | null;
  rest_minutes: number | null;
  exercise_minutes: number | null;
  schedule_count: number | null;
  subjective_stress: number | null;
  subjective_fatigue: number | null;
  negative_emotion_probability: number | null;
  status: BaselineStatus;
  algorithm_version: string;
  created_at: string;
}

// app/schemas/baseline.py 기준. window_days 생략 시 서버 기본값 14일.
export interface BaselineCreate {
  as_of_date: string; // YYYY-MM-DD, 미래 불가
  window_days?: number; // 14~28
}

/** 최근(as_of_date 기준 최대 28일 전까지) 기록으로 평소 기준(baseline)을 다시
 *  계산해 저장한다. 실제로 기록된 날짜가 최소 일수(7일, app/services/baselines.py의
 *  MINIMUM_SAMPLE_DAYS) 미만이면 status: "insufficient"로 저장되고 에러는 아니다 --
 *  이 호출 자체는 baseline이 아직 준비되지 않았다는 이유로 실패하지 않는다.
 *
 *  이 엔드포인트를 호출하는 게 baseline이 만들어지는 유일한 경로다(서버에 자동
 *  생성/스케줄러가 없음) -- risk evaluation·recovery report가 요구하는 "평소 기준"이
 *  실제로 존재하려면 어디선가는 반드시 이걸 불러줘야 한다.
 */
export async function createBaseline(payload: BaselineCreate): Promise<BaselineRead> {
  return apiFetch<BaselineRead>("/api/v1/baselines", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// 준비된(ready) baseline이 없으면 서버가 404를 정상 응답으로 준다 -- "아직 없음"이라
// null로 돌려서 호출부가 에러 처리 대신 자연스럽게 이어가게 한다.
export async function getLatestReadyBaseline(): Promise<BaselineRead | null> {
  try {
    return await apiFetch<BaselineRead>("/api/v1/baselines/latest-ready");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
