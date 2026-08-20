import { useEffect, useState } from "react";
import { Brand, NoteMark, SummaryLine, Tag, TextButton } from "../components/common";
import type { AppScreen } from "../types";
import { getKBatResult, type KBatResultResponse, type KBatRiskLevel } from "../api/assessments";
import { getBehavioralRecordsRange, type BehavioralRecordRead } from "../api/behavioralRecords";
import { getLatestReadyBaseline, type BaselineRead } from "../api/baselines";
import { getLatestRecoveryReport, type RecoveryReportResponse } from "../api/recoveryReports";
import { BURNOUT_SUBSCALES } from "../../data/burnoutQuestions";

// 결과 화면에서만 쓰는 영역 순서 + 라벨. 문항 정의(burnoutQuestions.ts)를
// 다시 베끼지 않고 그대로 참조해서, 설문 화면과 결과 화면의 영역 이름이
// 갈라지지 않게 한다.
const DOMAIN_ROWS: { key: keyof Pick<
  NonNullable<KBatResultResponse["result"]>,
  "exhaustion_average" | "mental_distance_average" | "cognitive_control_average" | "emotional_control_average"
>; subscaleKey: (typeof BURNOUT_SUBSCALES)[number]["key"] }[] = [
  { key: "exhaustion_average", subscaleKey: "exhaustion" },
  { key: "mental_distance_average", subscaleKey: "mental-distance" },
  { key: "cognitive_control_average", subscaleKey: "cognitive-control" },
  { key: "emotional_control_average", subscaleKey: "emotional-control" },
];

function domainLabel(subscaleKey: (typeof BURNOUT_SUBSCALES)[number]["key"]): string {
  return BURNOUT_SUBSCALES.find(s => s.key === subscaleKey)?.nameKo ?? subscaleKey;
}

// 요구사항 3. 판정 기준(경계값 계산)은 백엔드(app/domain/kbat/scoring.py)가
// 이미 끝낸 상태로 risk_level만 내려온다 -- 여기서는 그 결과에 맞는
// 문구/색만 고른다. 소수점 반올림은 여기(표시용)에서만 한다.
const RISK_COPY: Record<
  KBatRiskLevel,
  { emoji: string; label: string; sublabel: string; tone: "sage" | "ochre" | "clay"; description: string }
> = {
  good: {
    emoji: "🟢",
    label: "양호",
    sublabel: "안전",
    tone: "sage",
    description: "정상적인 스트레스 수준입니다. 현재의 리듬을 유지하세요.",
  },
  caution: {
    emoji: "🟠",
    label: "주의",
    sublabel: "위험군",
    tone: "ochre",
    description: "번아웃 초기 증상이 나타납니다. 휴식과 직무 환경 개선이 필요합니다.",
  },
  warning: {
    emoji: "🔴",
    label: "경고",
    sublabel: "고위험군",
    tone: "clay",
    description: "심각한 번아웃 상태입니다. 전문가 상담이나 치료적 개입을 권장합니다.",
  },
};

function formatScore(value: number): string {
  return value.toFixed(2);
}

function formatMinutes(min: number): string {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  if (h === 0) return `${m}분`;
  if (m === 0) return `${h}시간`;
  return `${h}시간 ${m}분`;
}

// "최근 21일 동안 꾸준히..." 예시가 요구사항이 준 유일한 구체 수치라 그대로
// 기준선으로 쓴다 -- 임의의 숫자를 새로 만들지 않는다. 7일 미만은 이 화면에
// 아예 오지 않는다(그건 "insufficient_records" 화면의 몫).
const HIGH_CONFIDENCE_DAYS = 21;

type ConfidenceTier = "high" | "medium";

function confidenceTier(recordedDays: number): ConfidenceTier {
  return recordedDays >= HIGH_CONFIDENCE_DAYS ? "high" : "medium";
}

const CONFIDENCE_COPY: Record<ConfidenceTier, { label: string; tone: "sage" | "ochre"; description: (days: number) => string }> = {
  high: {
    label: "높음",
    tone: "sage",
    description: days => `최근 ${days}일 동안 꾸준히 생활 기록을 남겼고 설문 응답도 정상적으로 완료되어, 지금 분석 결과를 참고하기에 충분한 데이터가 있어요.`,
  },
  medium: {
    label: "보통",
    tone: "ochre",
    description: () => "최근 생활 기록이 일부 부족해요. 지금 결과는 참고용으로 확인해 주세요. 더 정확한 개인 생활 패턴을 확인하려면 꾸준히 생활 기록을 남겨주세요.",
  },
};

type MetricKey = "sleep_minutes" | "rest_minutes" | "work_or_study_minutes" | "exercise_minutes";

const LIFESTYLE_METRICS: { key: MetricKey; label: string; baselineKey: keyof BaselineRead }[] = [
  { key: "sleep_minutes", label: "수면", baselineKey: "sleep_minutes" },
  { key: "rest_minutes", label: "휴식", baselineKey: "rest_minutes" },
  { key: "work_or_study_minutes", label: "공부 · 업무", baselineKey: "study_work_minutes" },
  { key: "exercise_minutes", label: "운동", baselineKey: "exercise_minutes" },
];

// 최근 값이 평소 기준보다 이 비율 이상 벗어나야 "부족/늘었어요"로 말한다.
// app/domain/risk/config.py의 adverse_change_points가 10%를 첫 유의미한
// 변화 구간으로 쓰는 것과 같은 기준을 재사용한다 -- 이 앱이 이미 "의미
// 있는 변화"로 취급하는 폭이다.
const NOTABLE_CHANGE_THRESHOLD = 0.1;

function averageOf(records: BehavioralRecordRead[], key: MetricKey): number | null {
  const values = records.map(r => r[key]).filter((v): v is number => v !== null);
  if (values.length === 0) return null;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

function comparisonLabel(recent: number, baseline: number): { text: string; arrow: string } | null {
  if (baseline <= 0) return null;
  const change = (recent - baseline) / baseline;
  if (change <= -NOTABLE_CHANGE_THRESHOLD) return { text: "평소보다 부족해요", arrow: "↓" };
  if (change >= NOTABLE_CHANGE_THRESHOLD) return { text: "평소보다 늘었어요", arrow: "↑" };
  return { text: "평소와 비슷해요", arrow: "→" };
}

export function BurnoutResultView({ go }: { go: (screen: AppScreen) => void }) {
  const [data, setData] = useState<KBatResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  // ready 상태일 때만 필요한 보조 데이터 -- 전부 이미 있는 API를 그대로
  // 재사용한다. 하나라도 못 불러와도 결과 화면 자체는 그대로 보여준다
  // (있는 데이터만 보여주고, 없는 건 임의로 채우지 않는다).
  const [recentRecords, setRecentRecords] = useState<BehavioralRecordRead[] | null>(null);
  const [baseline, setBaseline] = useState<BaselineRead | null>(null);
  const [report, setReport] = useState<RecoveryReportResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await getKBatResult();
        if (!cancelled) setData(result);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "번아웃 결과를 불러오지 못했습니다.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (data?.state !== "ready") return;
    let cancelled = false;
    const today = new Date().toISOString().slice(0, 10);
    const sevenDaysAgo = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    (async () => {
      const [recordsResult, baselineResult, reportResult] = await Promise.allSettled([
        getBehavioralRecordsRange(sevenDaysAgo, today),
        getLatestReadyBaseline(),
        getLatestRecoveryReport(),
      ]);
      if (cancelled) return;
      if (recordsResult.status === "fulfilled") setRecentRecords(recordsResult.value);
      if (baselineResult.status === "fulfilled") setBaseline(baselineResult.value);
      if (reportResult.status === "fulfilled") setReport(reportResult.value);
    })();
    return () => {
      cancelled = true;
    };
  }, [data?.state]);

  if (loading) {
    return (
      <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
        <div className="mx-auto max-w-2xl">
          <Brand />
          <p className="mt-16 text-sm text-muted-foreground">불러오는 중...</p>
        </div>
      </main>
    );
  }

  // 진짜 조회 실패(네트워크/서버 오류) -- "결과 없음"과는 다르게 취급한다.
  if (error || !data) {
    return (
      <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
        <div className="mx-auto max-w-2xl">
          <Brand />
          <p className="mt-16 text-sm text-red-500">{error ?? "번아웃 결과를 불러오지 못했습니다."}</p>
          <TextButton onClick={() => go("home")}>홈으로 돌아가기</TextButton>
        </div>
      </main>
    );
  }

  if (data.state === "not_taken") {
    return (
      <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
        <div className="mx-auto max-w-2xl">
          <Brand />
          <div className="mt-20 max-w-xl">
            <p className="text-xs tracking-[.08em] text-muted-foreground">번아웃 자가진단</p>
            <h1 className="mt-5 font-serif text-[30px] leading-[1.55] tracking-[-.05em]">
              아직 번아웃 자가진단을
              <br />
              완료하지 않았어요.
              <NoteMark />
            </h1>
            <p className="mt-5 text-sm leading-7 text-muted-foreground">
              몇 분이면 끝나는 설문이에요. 완료하고 일상기록을 이어가면, 영역별 결과와 종합 상태를 볼 수 있어요.
            </p>
            <button onClick={() => go("burnout")} className="mt-9 rounded-lg bg-[#68796b] px-4 py-3 text-sm font-semibold text-white">
              자가진단 시작하기
            </button>
          </div>
        </div>
      </main>
    );
  }

  if (data.state === "insufficient_records") {
    const remaining = Math.max(0, data.minimum_required_days - data.recorded_days);
    return (
      <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
        <div className="mx-auto max-w-2xl">
          <Brand />
          <div className="mt-20 max-w-xl">
            <p className="text-xs tracking-[.08em] text-muted-foreground">분석 신뢰도 · 낮음</p>
            <h1 className="mt-5 font-serif text-[30px] leading-[1.55] tracking-[-.05em]">
              아직 충분한 기록이
              <br />
              쌓이지 않았어요.
              <NoteMark />
            </h1>
            <p className="mt-5 text-sm leading-7 text-muted-foreground">
              아직 수집된 생활 데이터가 충분하지 않아요. 설문 결과와 일상기록을 함께 봐야 더 정확해요. 일상기록을 {data.minimum_required_days}일 동안 작성한 후 다시 확인해 주세요.
            </p>
            <div className="mt-8 flex items-center gap-3">
              <div className="h-1.5 flex-1 max-w-[220px] rounded-full bg-[#e4dfd7]">
                <div
                  className="h-1.5 rounded-full bg-[#68796b] transition-all"
                  style={{ width: `${Math.min(100, (data.recorded_days / data.minimum_required_days) * 100)}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground">
                {data.recorded_days} / {data.minimum_required_days}일
              </span>
            </div>
            {remaining > 0 && <p className="mt-2 text-xs text-muted-foreground">{remaining}일만 더 기록하면 결과를 볼 수 있어요.</p>}
            <button onClick={() => go("record")} className="mt-8 rounded-lg bg-[#68796b] px-4 py-3 text-sm font-semibold text-white">
              오늘 기록 남기기
            </button>
          </div>
        </div>
      </main>
    );
  }

  // state === "ready"
  const { result } = data;
  if (!result) {
    // 계약상 ready면 result가 항상 채워지지만, 방어적으로 한 번 더 확인한다.
    return (
      <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
        <div className="mx-auto max-w-2xl">
          <Brand />
          <p className="mt-16 text-sm text-muted-foreground">번아웃 결과를 불러오지 못했습니다.</p>
        </div>
      </main>
    );
  }
  const copy = RISK_COPY[result.risk_level];
  const tier = confidenceTier(data.recorded_days);
  const tierCopy = CONFIDENCE_COPY[tier];
  const notableChanges = report?.facts.changes.filter(c => c.fact_text).map(c => c.fact_text) ?? [];

  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-2xl">
        <Brand />
        <div className="mt-16 max-w-xl">
          {/* 분석 신뢰도 -- 설문+기록을 종합한 결과를 얼마나 참고할 만한지.
              통계적 정확도가 아니라 데이터 충분성 기준의 정성적 단계다. */}
          <p className="text-xs tracking-[.08em] text-muted-foreground">분석 신뢰도</p>
          <div className="mt-3 flex items-center gap-3">
            <Tag tone={tierCopy.tone}>{tierCopy.label}</Tag>
            <span className="text-xs text-muted-foreground">
              생활 기록 {data.recorded_days}{tier === "medium" ? `/${HIGH_CONFIDENCE_DAYS}` : ""}일 · 설문 응답 완료
            </span>
          </div>
          <p className="mt-3 text-sm leading-7 text-muted-foreground">{tierCopy.description(data.recorded_days)}</p>

          <div className="mt-9 border-t border-border pt-8">
            <p className="text-xs tracking-[.08em] text-muted-foreground">번아웃 자가진단 결과 · 설문 + 최근 일상기록 종합</p>
            <div className="mt-5">
              <Tag tone={copy.tone}>
                {copy.emoji} {copy.label} ({copy.sublabel})
              </Tag>
            </div>
            <h1 className="mt-4 font-serif text-[30px] leading-[1.55] tracking-[-.05em]">
              전체 평균 {formatScore(result.total_average)}
              <span className="text-muted-foreground"> / 5.00</span>
              <NoteMark />
            </h1>
            <p className="mt-5 text-sm leading-7 text-muted-foreground">{copy.description}</p>

            <button
              onClick={() => setExpanded(v => !v)}
              className="mt-8 text-sm text-[#536458] underline underline-offset-4"
            >
              {expanded ? "영역별 평균 접기" : "영역별 평균 자세히 보기"}
            </button>

            {expanded && (
              <div className="mt-4 divide-y divide-border border-y border-border">
                {DOMAIN_ROWS.map(row => (
                  <SummaryLine key={row.key} label={domainLabel(row.subscaleKey)} value={`${formatScore(result[row.key])} / 5.00`} />
                ))}
              </div>
            )}
          </div>

          {/* 나의 최근 생활 패턴 -- 실제로 남긴 일상기록만 보여준다. 평소
              기준(baseline)이 아직 없으면 비교 없이 숫자만 보여주고,
              해당 항목 기록이 아예 없으면 그 항목은 "기록 없음"으로만
              말한다 -- 임의의 값을 채우지 않는다. */}
          {recentRecords && recentRecords.length > 0 && (
            <div className="mt-9 border-t border-border pt-8">
              <p className="text-xs tracking-[.08em] text-muted-foreground">나의 최근 생활 패턴 · 최근 {recentRecords.length}일</p>
              <div className="mt-5 divide-y divide-border border-y border-border">
                {LIFESTYLE_METRICS.map(metric => {
                  const recentAvg = averageOf(recentRecords, metric.key);
                  const baselineAvg = baseline ? (baseline[metric.baselineKey] as number | null) : null;
                  const comparison = recentAvg !== null && baselineAvg ? comparisonLabel(recentAvg, baselineAvg) : null;
                  return (
                    <div className="grid grid-cols-[90px_1fr] gap-3 py-4" key={metric.key}>
                      <p className="text-sm">{metric.label}</p>
                      <div>
                        <p className="text-sm font-medium text-[#35332f]">
                          {recentAvg !== null ? `평균 ${formatMinutes(recentAvg)}` : "기록 없음"}
                        </p>
                        {comparison && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {comparison.arrow} {comparison.text}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 주요 변화 -- 생활 리포트(회복 계획 파이프라인)가 이미 계산해 둔
              사실 문장(fact_text)을 그대로 쓴다. 리포트가 아직 없으면
              섹션 자체를 보여주지 않는다(지어내지 않는다). */}
          {notableChanges.length > 0 && (
            <div className="mt-9 border-t border-border pt-8">
              <p className="text-xs tracking-[.08em] text-muted-foreground">주요 변화</p>
              <ul className="mt-4 space-y-2">
                {notableChanges.map((text, i) => (
                  <li key={i} className="text-sm leading-6 text-[#49423b]">
                    · {text}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-9 flex flex-wrap gap-5">
            <TextButton onClick={() => go("home")}>홈으로 돌아가기</TextButton>
          </div>
          <p className="mt-10 border-t border-border pt-5 text-xs leading-5 text-muted-foreground">
            이 결과는 의료적 진단이 아니며, 사용자가 기록한 생활 데이터와 설문 응답을 기반으로 현재 생활 패턴의 위험 신호를 참고하기 위한 결과입니다.
          </p>
        </div>
      </div>
    </main>
  );
}
