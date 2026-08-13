import { useEffect, useState } from "react";
import { ArrowRight, Pencil } from "lucide-react";
import { Hairline, SummaryLine, TextButton } from "../components/common";
import type { AppScreen } from "../types";
import {
  buildFieldMeta,
  createBehavioralRecord,
  getBehavioralRecordByDate,
  type NullableMetricKey,
} from "../api/behavioralRecords";
import { createEmotionAnalysis, type EmotionAnalysisRead } from "../api/emotionAnalyses";

function todayDateString() {
  return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
}

const TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

type MinuteField = "sleep_minutes" | "rest_minutes" | "work_or_study_minutes" | "exercise_minutes";

const MINUTE_FIELD_LABELS: [MinuteField, string][] = [
  ["sleep_minutes", "수면 시간"],
  ["rest_minutes", "휴식 시간"],
  ["work_or_study_minutes", "공부 · 업무 시간"],
  ["exercise_minutes", "운동 시간"],
];

function formatMinutes(min: number | null): string {
  if (min === null) return "";
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h === 0) return `${m}분`;
  if (m === 0) return `${h}시간`;
  return `${h}시간 ${m}분`;
}

export function RecordView({ go, editing = false }: { go: (screen: AppScreen) => void; editing?: boolean }) {
  const [step, setStep] = useState(1);
  const [saved, setSaved] = useState(false);
  const [emotionResult, setEmotionResult] = useState<EmotionAnalysisRead | null>(null);

  const [minuteValues, setMinuteValues] = useState<Record<MinuteField, number | null>>({
    sleep_minutes: null,
    rest_minutes: null,
    work_or_study_minutes: null,
    exercise_minutes: null,
  });
  const [editedByUser, setEditedByUser] = useState<Partial<Record<NullableMetricKey, boolean>>>({});

  // hs01/hs02 필수, hs03 선택 — app/clients/ai.py의 CoarseEmotionRequest 형식
  const [hs01, setHs01] = useState("");
  const [hs02, setHs02] = useState("");
  const [hs03, setHs03] = useState("");

  const [alreadyRecordedToday, setAlreadyRecordedToday] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const record = await getBehavioralRecordByDate(todayDateString());
        if (cancelled) return;
        setMinuteValues({
          sleep_minutes: record.sleep_minutes,
          rest_minutes: record.rest_minutes,
          work_or_study_minutes: record.work_or_study_minutes,
          exercise_minutes: record.exercise_minutes,
        });
        setAlreadyRecordedToday(true);
      } catch {
        // 오늘 기록이 아직 없는 정상적인 경우 (404)
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function handleMinuteChange(field: MinuteField, raw: string) {
    const parsed = raw.trim() === "" ? null : Number(raw);
    setMinuteValues(v => ({ ...v, [field]: Number.isNaN(parsed) ? v[field] : parsed }));
    setEditedByUser(v => ({ ...v, [field]: true }));
  }

  async function handleNext() {
    if (alreadyRecordedToday) {
      setStep(2);
      return;
    }

    setError(null);
    setSaving(true);
    try {
      const allValues: Record<NullableMetricKey, unknown> = {
        sleep_minutes: minuteValues.sleep_minutes,
        bedtime: null,
        wake_time: null,
        steps: null,
        active_minutes: null,
        exercise_minutes: minuteValues.exercise_minutes,
        work_or_study_minutes: minuteValues.work_or_study_minutes,
        rest_minutes: minuteValues.rest_minutes,
        schedule_count: null, // TODO: 논의 필요
        subjective_fatigue: null, // TODO: 척도 확정 필요
      };
      const { source_by_field, coverage_by_field } = buildFieldMeta(allValues, editedByUser);

      await createBehavioralRecord({
        date: todayDateString(),
        time_zone: TIME_ZONE,
        sleep_minutes: minuteValues.sleep_minutes,
        bedtime: null,
        wake_time: null,
        steps: null,
        active_minutes: null,
        exercise_minutes: minuteValues.exercise_minutes,
        work_or_study_minutes: minuteValues.work_or_study_minutes,
        rest_minutes: minuteValues.rest_minutes,
        schedule_count: null,
        subjective_fatigue: null,
        source_by_field,
        coverage_by_field,
      });
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "생활 기록 저장 중 오류가 발생했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSubmitEmotion() {
    setError(null);

    if (hs01.trim().length === 0 || hs02.trim().length === 0) {
      setError("첫 번째와 두 번째 항목은 꼭 채워 주세요.");
      return;
    }

    setSaving(true);
    try {
      const result = await createEmotionAnalysis({
        record_date: todayDateString(),
        hs01,
        hs02,
        hs03: hs03.trim().length > 0 ? hs03 : null,
      });
      setEmotionResult(result);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "감정 분석 저장 중 오류가 발생했습니다.");
    } finally {
      setSaving(false);
    }
  }

  if (saved) {
    return (
      <section className="mx-auto max-w-3xl">
        <p className="text-xs text-muted-foreground">오늘의 기록</p>
        <h1 className="mt-4 font-serif text-[31px] leading-[1.5] tracking-[-.05em]">
          오늘 남긴 기록을 정리했어요.
        </h1>
        <p className="mt-5 text-sm leading-7 text-muted-foreground">오늘 남긴 기록을 바탕으로 한 하루의 요약이에요.</p>
        <div className="mt-9 divide-y divide-border border-y border-border">
          <SummaryLine label="수면" value={formatMinutes(minuteValues.sleep_minutes) || "기록 없음"} />
          <SummaryLine label="휴식" value={formatMinutes(minuteValues.rest_minutes) || "기록 없음"} />
          <SummaryLine
            label="오늘의 마음"
            value={
              emotionResult?.provisional
                ? "판단 보류 (중립에 가까움)"
                : emotionResult?.emotion ?? "분석 중"
            }
          />
        </div>
        {emotionResult?.is_uncertain && (
          <p className="mt-4 text-xs text-muted-foreground">
            이번 분석은 확신도가 낮아 참고용으로만 봐주세요.
          </p>
        )}
        <div className="mt-8 flex flex-wrap gap-5">
          <TextButton onClick={() => go("home")}>홈으로 돌아가기</TextButton>
        </div>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="mx-auto max-w-3xl">
        <p className="text-sm text-muted-foreground">불러오는 중...</p>
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-3xl">
      <p className="text-xs text-muted-foreground">오늘의 기록</p>
      <h1 className="mt-4 font-serif text-[31px] tracking-[-.05em]">{editing ? "기록을 다시 살펴볼까요?" : "오늘 하루를 남겨볼까요?"}</h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">정확하지 않아도 괜찮아요. 기억나는 만큼만 적어 주세요.</p>
      {alreadyRecordedToday && step === 1 && (
        <p className="mt-3 text-xs text-[#8d5541]">오늘 기록은 이미 저장돼 있어요. 지금은 수정 기능이 준비 중이라 값만 확인할 수 있어요.</p>
      )}
      <div className="mt-9 flex items-center gap-3 text-xs">
        <span className="text-[#68796b]">01 생활</span>
        <span className="h-px w-10 bg-border" />
        <span className={step === 2 ? "text-[#68796b]" : "text-muted-foreground"}>02 마음</span>
      </div>
      <Hairline className="mt-3" />
      <div className="mt-7">
        {step === 1 ? (
          <>
            <p className="text-xs leading-5 text-muted-foreground">기기에서 가져온 값이 있으면 우선 채워드려요. 다르면 직접 고쳐 주세요.</p>
            <div className="mt-5 grid gap-x-10 border-b border-border sm:grid-cols-2">
              {MINUTE_FIELD_LABELS.map(([field, label], i) => (
                <div key={field} className={`flex items-center justify-between border-t border-border py-4 ${i === 0 ? "sm:border-t-0" : ""}`}>
                  <div>
                    <p className="text-sm text-muted-foreground">{label}</p>
                    <p className="mt-1 text-[11px] text-[#5a7160]">
                      {editedByUser[field] ? "직접 수정됨" : minuteValues[field] !== null ? "기기 연동" : "기록 없음"}
                    </p>
                  </div>
                  <label className="flex items-center gap-2">
                    <input
                      aria-label={`${label} 수정 (분)`}
                      type="number"
                      min={0}
                      max={1440}
                      disabled={alreadyRecordedToday}
                      value={minuteValues[field] ?? ""}
                      onChange={e => handleMinuteChange(field, e.target.value)}
                      placeholder="분"
                      className="w-24 border-b border-transparent bg-transparent py-1 text-right text-sm font-medium outline-none focus:border-[#68796b] disabled:opacity-60"
                    />
                    <Pencil size={14} strokeWidth={1.5} className="text-muted-foreground" />
                  </label>
                </div>
              ))}
            </div>

            {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

            <button
              onClick={handleNext}
              disabled={saving}
              className="mt-8 inline-flex items-center gap-2 rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
            >
              {saving ? "저장 중..." : "다음"} <ArrowRight size={15} />
            </button>
          </>
        ) : (
          <>
            <p className="font-serif text-xl">오늘 하루, 어떤 일이 있었나요?</p>
            <p className="mt-2 text-xs text-muted-foreground">
              적어주신 내용을 바탕으로 오늘의 감정 상태를 분석해드려요. 감정을 직접 고르지 않아도 괜찮아요.
            </p>

            <label className="mt-7 block text-sm text-muted-foreground">
              오늘 있었던 일 (필수)
              <textarea
                value={hs01}
                onChange={e => setHs01(e.target.value)}
                maxLength={2000}
                placeholder="예: 면접 준비 때문에 계속 긴장되고 제대로 쉬지 못했다."
                className="mt-3 min-h-24 w-full border-y border-border bg-transparent py-3 text-sm leading-6 text-foreground outline-none focus:border-[#68796b]"
              />
            </label>

            <label className="mt-6 block text-sm text-muted-foreground">
              그때 든 생각이나 느낌 (필수)
              <textarea
                value={hs02}
                onChange={e => setHs02(e.target.value)}
                maxLength={2000}
                placeholder="예: 잘 해내지 못할까 봐 계속 불안했다."
                className="mt-3 min-h-24 w-full border-y border-border bg-transparent py-3 text-sm leading-6 text-foreground outline-none focus:border-[#68796b]"
              />
            </label>

            <label className="mt-6 block text-sm text-muted-foreground">
              덧붙이고 싶은 말 (선택)
              <textarea
                value={hs03}
                onChange={e => setHs03(e.target.value)}
                maxLength={2000}
                placeholder="더 남기고 싶은 이야기가 있다면 적어 주세요."
                className="mt-3 min-h-20 w-full border-y border-border bg-transparent py-3 text-sm leading-6 text-foreground outline-none focus:border-[#68796b]"
              />
            </label>

            {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

            <button
              onClick={handleSubmitEmotion}
              disabled={saving}
              className="mt-7 rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
            >
              {saving ? "분석 중..." : "기록 남기기"}
            </button>
          </>
        )}
      </div>
    </section>
  );
}