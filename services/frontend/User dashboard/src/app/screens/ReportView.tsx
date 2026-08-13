import { useEffect, useState } from "react";
import { NoteMark, Tag, TextButton } from "../components/common";
import type { AppScreen } from "../types";
import {
  getLatestRecoveryReport,
  type RecoveryReportResponse,
  type ReportMetric,
  type RiskLevel,
} from "../api/recoveryReports";

const METRIC_LABELS: Record<ReportMetric, string> = {
  sleep_minutes: "수면",
  work_or_study_minutes: "공부 · 업무",
  rest_minutes: "휴식",
  exercise_minutes: "운동",
  schedule_count: "일정 개수",
  negative_emotion_probability: "부정 감정 비율",
  subjective_stress: "주관적 스트레스",
  subjective_fatigue: "주관적 피로도",
};

const RISK_LABELS: Record<RiskLevel, string> = {
  low: "낮음",
  moderate: "보통",
  high: "높음",
  very_high: "매우 높음",
};

function formatMetricValue(metric: ReportMetric, value: number): string {
  switch (metric) {
    case "sleep_minutes":
    case "work_or_study_minutes":
    case "rest_minutes":
    case "exercise_minutes": {
      const h = Math.floor(value / 60);
      const m = Math.round(value % 60);
      if (h === 0) return `${m}분`;
      if (m === 0) return `${h}시간`;
      return `${h}시간 ${m}분`;
    }
    case "schedule_count":
      return `${Math.round(value)}개`;
    case "negative_emotion_probability":
      return `${Math.round(value * 100)}%`;
    default:
      return `${value}`;
  }
}

function formatPeriodLabel(start: string, end: string): string {
  const [, sm, sd] = start.split("-");
  const [, em, ed] = end.split("-");
  return `${Number(sm)}월 ${Number(sd)}일 — ${Number(em)}월 ${Number(ed)}일`;
}

export function ReportView({ go }: { go: (screen: AppScreen) => void }) {
  const [report, setReport] = useState<RecoveryReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getLatestRecoveryReport();
        if (!cancelled) setReport(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "리포트를 불러오지 못했습니다.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <section className="max-w-5xl">
        <p className="text-sm text-muted-foreground">불러오는 중...</p>
      </section>
    );
  }

  if (error) {
    return (
      <section className="max-w-5xl">
        <p className="text-sm text-red-500">{error}</p>
      </section>
    );
  }

  if (!report) {
    return (
      <section className="max-w-5xl">
        <p className="text-sm text-muted-foreground">아직 생성된 리포트가 없어요. 기록이 조금 더 쌓이면 만들어드릴게요.</p>
      </section>
    );
  }

  const { facts, content, selected_actions, disclaimer } = report;
  const numericChanges = facts.changes.filter(c => c.metric !== null && c.recent_value !== null);

  const suggestions = selected_actions.map(action => {
    const reason = content.recommendation_descriptions.find(r => r.action_id === action.id)?.reason;
    return { action, reason };
  });

  return (
    <section className="max-w-5xl">
      <p className="text-xs text-muted-foreground">생활 리포트 · {formatPeriodLabel(report.period_start, report.period_end)}</p>
      <h1 className="mt-4 font-serif text-[31px] leading-[1.45] tracking-[-.05em]">
        {content.headline}
        <NoteMark />
      </h1>
      <p className="mt-5 max-w-2xl text-sm leading-7 text-muted-foreground">{content.summary}</p>

      <div className="mt-9 border-l-2 border-[#be765b] pl-3">
        <Tag tone={facts.risk_level === "high" || facts.risk_level === "very_high" ? "ochre" : "sage"}>
          생활 흐름 변화 · {RISK_LABELS[facts.risk_level]}
        </Tag>
        <span className="ml-3 text-xs text-muted-foreground">
          {facts.is_provisional ? "데이터가 더 쌓이면 더 정확해져요." : "기록을 바탕으로 한 참고 정보예요."}
        </span>
      </div>

      <section className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div>
          <h2 className="font-serif text-xl">평소와 최근의 비교</h2>
          {numericChanges.length === 0 ? (
            <p className="mt-5 text-sm text-muted-foreground">비교할 만큼 데이터가 아직 충분하지 않아요.</p>
          ) : (
            <div className="mt-5 divide-y divide-border border-y border-border">
              {numericChanges.map(change => {
                const metric = change.metric as ReportMetric;
                const width =
                  change.baseline_value && change.baseline_value > 0
                    ? Math.min(100, Math.round(((change.recent_value ?? 0) / change.baseline_value) * 100))
                    : 50;
                return (
                  <div className="grid grid-cols-[90px_1fr] gap-3 py-4" key={change.factor_code}>
                    <p className="text-sm">{METRIC_LABELS[metric]}</p>
                    <div>
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">
                          {change.baseline_value !== null ? `평소 ${formatMetricValue(metric, change.baseline_value)}` : "평소 데이터 없음"}
                        </span>
                        <span className="font-medium text-[#8d5541]">
                          최근 {formatMetricValue(metric, change.recent_value ?? 0)}
                        </span>
                      </div>
                      <div className="mt-2 h-[3px] bg-[#e4dfd7]">
                        <div className="h-[3px] bg-[#778a93]" style={{ width: `${width}%` }} />
                      </div>
                      <p className="mt-1.5 text-[11px] text-muted-foreground">{change.fact_text}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <aside className="border-t border-border pt-5 lg:border-l lg:border-t-0 lg:pl-7">
          <p className="text-xs text-muted-foreground">기록에서 보인 변화</p>
          <blockquote className="mt-4 font-serif text-lg leading-8 text-[#504a43]">{content.weekly_observation}</blockquote>
        </aside>
      </section>

      <section className="mt-12 border-t border-border pt-8">
        <p className="text-xs text-muted-foreground">{content.recommendation_intro}</p>
        <div className="mt-5 divide-y divide-border border-y border-border">
          {suggestions.map(({ action, reason }, i) => (
            <div className="flex items-center gap-4 py-4" key={action.id}>
              <span className="font-serif text-lg text-[#aaa197]">0{i + 1}</span>
              <div className="flex-1">
                <p className="text-sm font-medium">
                  {action.title}
                  {action.duration_minutes ? ` · ${action.duration_minutes}분` : ""}
                </p>
                {reason && <p className="mt-1 text-xs text-muted-foreground">{reason}</p>}
              </div>
              <button className="text-xs font-semibold text-[#68796b]">추가</button>
            </div>
          ))}
        </div>
        <TextButton onClick={() => go("plan")}>이번 주에 해보기</TextButton>
      </section>

      <p className="mt-12 border-t border-border pt-5 text-xs leading-5 text-muted-foreground">{disclaimer}</p>
    </section>
  );
}