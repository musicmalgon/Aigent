import { apiFetch, ApiError } from "./client";

// packages/contracts/schemas/behavioral_daily_record.schema.json 기준
export const NULLABLE_METRIC_KEYS = [
  "sleep_minutes",
  "bedtime",
  "wake_time",
  "steps",
  "active_minutes",
  "exercise_minutes",
  "work_or_study_minutes",
  "rest_minutes",
  "schedule_count",
  "subjective_fatigue",
] as const;

export type NullableMetricKey = (typeof NULLABLE_METRIC_KEYS)[number];

export type DataSource = "health_platform" | "manual" | "synthetic" | "not_provided";
export type DataCoverage = "complete" | "partial" | "unavailable";

export interface BehavioralRecordCreate {
  date: string; // YYYY-MM-DD, 보낸 time_zone 기준 오늘보다 미래 불가
  time_zone: string; // IANA 시간대, 예: "Asia/Seoul"

  sleep_minutes: number | null; // 0~1440
  bedtime: string | null; // "HH:MM:SS"
  wake_time: string | null; // "HH:MM:SS"
  steps: number | null; // 0 이상 정수
  active_minutes: number | null; // 0~1440
  exercise_minutes: number | null; // 0~1440
  work_or_study_minutes: number | null; // 0~1440
  rest_minutes: number | null; // 0~1440
  schedule_count: number | null; // 0 이상 정수
  subjective_fatigue: number | null; // 0 이상, 상한 미정

  // 10개 키 전부 필수. 값이 null인 필드는 반드시 coverage: "unavailable".
  // 값이 있는 필드는 source가 "not_provided"면 안 되고, coverage는 "complete"|"partial".
  source_by_field: Record<NullableMetricKey, DataSource>;
  coverage_by_field: Record<NullableMetricKey, DataCoverage>;
}

export interface BehavioralRecordRead extends BehavioralRecordCreate {
  user_id: string;
}

/** 필드별 값 + "기기에서 가져왔는지 사람이 고쳤는지" 여부를 받아서
 *  source_by_field / coverage_by_field를 자동으로 채워주는 헬퍼.
 *  - 값이 null: source "not_provided" / coverage "unavailable"
 *  - 기기 데이터 그대로: source "health_platform" / coverage "complete"
 *  - 사람이 직접 입력했거나 기기 값을 고침: source "manual" / coverage "complete" */
export function buildFieldMeta(
  values: Partial<Record<NullableMetricKey, unknown>>,
  editedByUser: Partial<Record<NullableMetricKey, boolean>> = {}
): { source_by_field: Record<NullableMetricKey, DataSource>; coverage_by_field: Record<NullableMetricKey, DataCoverage> } {
  const source_by_field = {} as Record<NullableMetricKey, DataSource>;
  const coverage_by_field = {} as Record<NullableMetricKey, DataCoverage>;

  for (const key of NULLABLE_METRIC_KEYS) {
    if (values[key] === null || values[key] === undefined) {
      source_by_field[key] = "not_provided";
      coverage_by_field[key] = "unavailable";
    } else {
      source_by_field[key] = editedByUser[key] ? "manual" : "health_platform";
      coverage_by_field[key] = "complete";
    }
  }

  return { source_by_field, coverage_by_field };
}

export async function createBehavioralRecord(
  payload: BehavioralRecordCreate
): Promise<BehavioralRecordRead> {
  return apiFetch<BehavioralRecordRead>("/api/v1/behavioral-records", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// POST와 동일한 본문 형식. payload.date는 recordDate와 같아야 하고, 해당 날짜 기록이 없으면 404.
export async function updateBehavioralRecord(
  recordDate: string,
  payload: BehavioralRecordCreate
): Promise<BehavioralRecordRead> {
  return apiFetch<BehavioralRecordRead>(`/api/v1/behavioral-records/${recordDate}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

// 그 날짜에 기록이 없으면 백엔드가 404를 정상 응답으로 준다 -- 에러가
// 아니라 "없음"이므로 null로 돌려서 화면(OverlayContent)이 이미 갖고
// 있는 "이 날짜의 기록을 찾을 수 없어요" 안내로 자연스럽게 이어지게 한다.
export async function getBehavioralRecordByDate(
  recordDate: string
): Promise<BehavioralRecordRead | null> {
  try {
    return await apiFetch<BehavioralRecordRead>(`/api/v1/behavioral-records/${recordDate}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

// 범위 없이 호출하면 최근 14일(UTC), 범위 지정 시 최대 28일까지, 최신순 정렬로 옴
export async function getBehavioralRecordsRange(
  dateFrom?: string,
  dateTo?: string
): Promise<BehavioralRecordRead[]> {
  const params = new URLSearchParams();
  if (dateFrom && dateTo) {
    params.set("date_from", dateFrom);
    params.set("date_to", dateTo);
  }
  const query = params.toString();
  return apiFetch<BehavioralRecordRead[]>(
    `/api/v1/behavioral-records${query ? `?${query}` : ""}`
  );
}