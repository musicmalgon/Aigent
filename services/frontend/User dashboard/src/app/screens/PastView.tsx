import { useEffect, useState } from "react";
import type { AppScreen } from "../types";
import { getBehavioralRecordsRange, type BehavioralRecordRead } from "../api/behavioralRecords";

function formatMinutes(min: number | null): string {
  if (min === null) return "기록 없음";
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h === 0) return `${m}분`;
  if (m === 0) return `${h}시간`;
  return `${h}시간 ${m}분`;
}

function formatDateLabel(dateStr: string): string {
  const [, month, day] = dateStr.split("-");
  return `${Number(month)}월 ${Number(day)}일`;
}

export function PastView({ openRecord, go }: { openRecord: (date: string) => void; go: (screen: AppScreen) => void }) {
  const [records, setRecords] = useState<BehavioralRecordRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // 범위 없이 호출 → 최근 14일(UTC), 최신순
        const data = await getBehavioralRecordsRange();
        if (!cancelled) setRecords(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "기록을 불러오지 못했습니다.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="mx-auto max-w-4xl">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-xs text-muted-foreground">지난 기록</p>
          <h1 className="mt-4 font-serif text-[31px] tracking-[-.05em]">하루하루 쌓인 흐름들</h1>
        </div>
        <button onClick={() => go("record")} className="text-sm text-[#536458] underline underline-offset-4">
          오늘 남기기
        </button>
      </div>

      {loading && <p className="mt-10 text-sm text-muted-foreground">불러오는 중...</p>}
      {error && <p className="mt-10 text-sm text-red-500">{error}</p>}
      {!loading && !error && records.length === 0 && (
        <p className="mt-10 text-sm text-muted-foreground">아직 남긴 기록이 없어요.</p>
      )}

      {!loading && !error && records.length > 0 && (
        <div className="mt-10 divide-y divide-border border-y border-border">
          {records.map(record => (
            <button
              onClick={() => openRecord(record.date)}
              className="block w-full py-7 text-left first:pt-5"
              key={record.date}
            >
              <p className="text-xs text-muted-foreground">{formatDateLabel(record.date)}</p>
              <p className="mt-3 max-w-xl font-serif text-lg leading-8 text-[#4c4842]">
                수면 {formatMinutes(record.sleep_minutes)} · 휴식 {formatMinutes(record.rest_minutes)}
              </p>
              <div className="mt-3 flex items-center justify-between gap-4">
                <p className="text-xs text-muted-foreground">
                  공부·업무 {formatMinutes(record.work_or_study_minutes)} · 운동 {formatMinutes(record.exercise_minutes)}
                </p>
                <span className="shrink-0 text-xs text-[#536458]">자세히 보기</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}