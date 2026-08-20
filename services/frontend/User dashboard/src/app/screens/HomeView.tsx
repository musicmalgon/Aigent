import { useEffect, useState } from "react";
import {
  Activity,
  Battery,
  Briefcase,
  CalendarDays,
  ChevronRight,
  Clock3,
  CloudRain,
  Flame,
  Footprints,
  Gauge,
  Moon,
  type LucideIcon,
} from "lucide-react";
import { ChangeRow, Hairline, NoteMark, Tag, TextButton } from "../components/common";
import type { AppScreen } from "../types";
import {
  getDashboard,
  getReadiness,
  type DashboardFactorCode,
  type DashboardResponse,
  type ReadinessState,
} from "../api/dashboard";
import type { RiskLevel } from "../api/recoveryReports";

// ReportView.tsx와 같은 문구를 써야 같은 위험도를 두 화면에서 다르게 읽지 않는다
const RISK_LABELS: Record<RiskLevel, string> = {
  low: "낮음",
  moderate: "보통",
  high: "높음",
  very_high: "매우 높음",
};

// 위험 요인 코드별 표시 정보. detail은 수치가 아니라 "어떤 기록에서 나온 신호인지"만
// 말한다 -- 대시보드 응답에는 코드만 있고 실제 값은 생활 리포트에 있기 때문이다.
const FACTOR_INFO: Record<DashboardFactorCode, { topic: string; title: string; detail: string; icon: LucideIcon }> = {
  sleep_decrease: { topic: "수면", title: "수면 시간이 줄었어요", detail: "수면 기록이 평소 기준보다 짧아요", icon: Moon },
  rest_decrease: { topic: "휴식", title: "쉴 틈이 줄었어요", detail: "휴식 기록이 평소 기준보다 짧아요", icon: Clock3 },
  workload_increase: { topic: "공부 · 업무", title: "공부·업무 시간이 늘었어요", detail: "공부·업무 기록이 평소 기준보다 길어요", icon: Briefcase },
  schedule_overload: { topic: "일정", title: "일정이 빽빽해졌어요", detail: "일정 개수가 평소 기준보다 많아요", icon: CalendarDays },
  exercise_decrease: { topic: "움직임", title: "몸을 움직인 시간이 줄었어요", detail: "운동 기록이 평소 기준보다 짧아요", icon: Footprints },
  negative_emotion_increase: { topic: "마음", title: "부정적인 감정이 늘었어요", detail: "감정 기록에서 평소보다 자주 보였어요", icon: CloudRain },
  high_negative_emotion: { topic: "마음", title: "부정적인 감정이 자주 보였어요", detail: "최근 감정 기록에서 비중이 높았어요", icon: CloudRain },
  subjective_stress: { topic: "스트레스", title: "스트레스를 높게 느꼈어요", detail: "직접 남긴 스트레스 응답 기준이에요", icon: Flame },
  subjective_fatigue: { topic: "피로", title: "피로감을 크게 느꼈어요", detail: "직접 남긴 피로감 응답 기준이에요", icon: Battery },
  insufficient_baseline: { topic: "평소 기준", title: "평소 기준을 만들 기록이 부족해요", detail: "기록이 더 쌓이면 비교가 정확해져요", icon: Gauge },
  insufficient_data: { topic: "최근 기록", title: "최근 기록이 아직 부족해요", detail: "며칠 더 남기면 흐름을 볼 수 있어요", icon: Activity },
};

// 값이 있는 코드만 문장으로 엮는다 -- "기록이 부족하다"는 신호는 흐름 설명이 될 수 없다.
const NON_SIGNAL_FACTORS: DashboardFactorCode[] = ["insufficient_baseline", "insufficient_data"];

// 기록 상태 사다리(app/services/dashboard.py)의 각 단계에서 정직하게 할 수 있는 말.
// 앞 세 단계는 아직 비교할 기준이 없으므로 변화나 추세를 언급하지 않는다.
const READINESS_COPY: Record<ReadinessState, { eyebrow: string; headline: string; body: string }> = {
  insufficient_records: {
    eyebrow: "기록을 모으는 중",
    headline: "아직은 흐름을 말하기에 기록이 조금 부족해요.",
    body: "며칠만 더 남겨주시면, 평소의 나를 기준으로 최근의 변화를 짚어볼 수 있어요.",
  },
  baseline_pending: {
    eyebrow: "평소의 기준을 만드는 중",
    headline: "평소의 리듬을 그려볼 만큼 기록이 모였어요.",
    body: "곧 나만의 기준이 만들어져요. 오늘 하루도 이어서 남겨보세요.",
  },
  baseline_ready: {
    eyebrow: "평소의 기준이 준비됨",
    headline: "이제 평소의 나와 최근의 나를 비교할 수 있어요.",
    body: "며칠 더 기록이 쌓이면 무엇이 달라졌는지 짚어드릴게요.",
  },
  risk_evaluation_ready: {
    eyebrow: "이번 주의 관찰",
    headline: "최근 기록에서 평소와 다른 부분이 보였어요.",
    body: "무엇이 왜 달라졌는지 정리한 리포트는 기록이 조금 더 쌓이면 만들어드릴게요.",
  },
  recovery_report_ready: {
    eyebrow: "이번 주의 관찰",
    headline: "최근 기록에서 평소와 다른 부분이 보였어요.",
    body: "오늘 할 수 있는 한 가지를 남기고, 생활의 빈자리를 조금씩 되찾아 봐요.",
  },
};

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function todayLabel(): string {
  const now = new Date();
  return `${now.getMonth() + 1}월 ${now.getDate()}일, ${WEEKDAYS[now.getDay()]}요일`;
}

/** 리포트가 있으면 리포트가 쓴 문장을, 없으면 실제 위험 요인 코드로만 문장을 만든다.
 *  둘 다 없으면 기록 단계에 맞는 정직한 안내 문구로 떨어진다. */
function heroHeadline(state: ReadinessState, data: DashboardResponse): string {
  if (data.latest_report) return data.latest_report.headline;

  const signals = (data.latest_risk?.top_factors ?? []).filter(code => !NON_SIGNAL_FACTORS.includes(code));
  if (signals.length > 0) {
    const topics = [...new Set(signals.slice(0, 2).map(code => FACTOR_INFO[code].topic))];
    return `최근 기록에서는 ${topics.join(" · ")}의 흐름이 평소와 달랐어요.`;
  }

  return READINESS_COPY[state].headline;
}

export function HomeView({ go, openRecord }: { go: (screen: AppScreen) => void; openRecord: () => void }) {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [readiness, setReadiness] = useState<ReadinessState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [dashboardData, readinessData] = await Promise.all([getDashboard(), getReadiness()]);
        if (cancelled) return;
        setDashboard(dashboardData);
        setReadiness(readinessData.state);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "홈 화면을 불러오지 못했습니다.");
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

  if (error || !dashboard || !readiness) {
    return (
      <section className="max-w-5xl">
        <p className="text-sm text-red-500">{error ?? "홈 화면을 불러오지 못했습니다."}</p>
      </section>
    );
  }

  const { record_status, baseline, latest_risk, latest_report } = dashboard;
  const copy = READINESS_COPY[readiness];
  const headline = heroHeadline(readiness, dashboard);
  const riskIsHigh = latest_risk?.level === "high" || latest_risk?.level === "very_high";

  return (
    <>
      <section className="grid gap-10 border-b border-border pb-11 lg:grid-cols-[minmax(0,1.22fr)_minmax(250px,.52fr)] lg:gap-16">
        <div className="pt-1">
          <p className="text-xs tracking-[.04em] text-muted-foreground">
            {todayLabel()} · {copy.eyebrow}
          </p>
          <h1 className="mt-5 max-w-2xl font-serif text-[31px] leading-[1.5] tracking-[-.055em] text-[#35332f] sm:text-[39px]">
            {headline}
            <NoteMark />
          </h1>
          <p className="mt-5 max-w-xl text-[14px] leading-7 text-muted-foreground">{copy.body}</p>
          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
            {latest_report && <TextButton onClick={() => go("report")}>왜 달라졌는지 보기</TextButton>}
            <button onClick={() => go("burnoutResult")} className="text-sm text-muted-foreground underline underline-offset-4">
              번아웃 자가진단 결과 보기
            </button>
            {record_status.today_recorded && (
              <button onClick={openRecord} className="text-sm text-muted-foreground underline underline-offset-4">
                오늘 기록 다시 보기
              </button>
            )}
          </div>
        </div>
        <div className="border-t border-border pt-5 lg:border-l lg:border-t-0 lg:pl-9 lg:pt-1">
          <p className="text-[11px] tracking-[.12em] text-muted-foreground">01 · TODAY</p>
          <p className="mt-4 font-serif text-[21px] leading-8 text-[#3c4540]">
            {record_status.today_recorded ? "오늘을 남겼어요." : "오늘을 남기면,"}
            <br />
            {record_status.today_recorded ? "내일도 이어가 봐요." : "내일의 흐름이 보여요."}
          </p>
          <Hairline className="my-5" />
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-sm text-muted-foreground">오늘의 기록</p>
              <p className="mt-1 text-sm leading-6 text-[#494741]">
                {record_status.today_recorded ? (
                  <>
                    오늘 기록은 마쳤어요.
                    <br />
                    언제든 고칠 수 있어요.
                  </>
                ) : (
                  <>
                    수면 · 휴식 · 마음을
                    <br />2분 안에 남길 수 있어요.
                  </>
                )}
              </p>
            </div>
            <span className="font-serif text-3xl text-[#d9a17d]">01</span>
          </div>
          <button onClick={() => go("record")} className="mt-5 inline-flex items-center gap-2 rounded-lg bg-[#68796b] px-3.5 py-2.5 text-sm font-semibold text-[#fffdf9]">
            {record_status.today_recorded ? "오늘 기록 고치기" : "오늘 하루 남기기"} <ChevronRight size={15} />
          </button>
        </div>
      </section>

      <section className="py-12">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <p className="text-xs tracking-[.04em] text-muted-foreground">02 · RECORDS</p>
            <h2 className="mt-3 font-serif text-[24px] tracking-[-.045em]">지금까지 쌓인 기록</h2>
          </div>
          <p className="max-w-xs text-xs leading-5 text-muted-foreground">
            {baseline?.status === "ready"
              ? `${baseline.sample_days}일치 기록으로 평소의 기준을 만들었어요.`
              : "기록이 충분히 모이면 평소의 기준이 만들어져요."}
          </p>
        </div>
        <div className="mt-8 grid gap-6 border-y border-border py-7 sm:grid-cols-2">
          <div>
            <p className="text-xs text-muted-foreground">남긴 날</p>
            <p className="mt-2 font-serif text-[28px] tracking-[-.04em] text-[#35332f]">{record_status.recorded_days}일</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">평소의 기준</p>
            <p className="mt-2 font-serif text-[28px] tracking-[-.04em] text-[#35332f]">
              {baseline?.status === "ready" ? "준비됨" : "만드는 중"}
            </p>
          </div>
        </div>
      </section>

      {record_status.recorded_days > 0 && (
        <section className="border-t border-border py-8">
          <button onClick={() => go("past")} className="flex w-full items-start justify-between gap-5 text-left">
            <div>
              <p className="text-xs tracking-[.04em] text-muted-foreground">지난 기록 이어보기</p>
              <p className="mt-3 font-serif text-lg leading-7">지금까지 남긴 하루들을 다시 볼 수 있어요.</p>
              <p className="mt-2 text-xs text-muted-foreground">기록 {record_status.recorded_days}일</p>
            </div>
            <ChevronRight className="mt-4 shrink-0 text-[#aaa197]" size={18} />
          </button>
        </section>
      )}

      <section className="grid gap-x-16 gap-y-10 border-t border-border py-12 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,.58fr)]">
        <div>
          <p className="text-xs tracking-[.04em] text-muted-foreground">03 · WHAT CHANGED</p>
          <h2 className="mt-3 font-serif text-[24px] tracking-[-.045em]">평소와 달라진 부분</h2>
          {latest_risk && latest_risk.top_factors.length > 0 ? (
            <div className="mt-6 divide-y divide-border border-y border-border">
              {latest_risk.top_factors.map((code, i) => (
                <ChangeRow
                  key={code}
                  index={String(i + 1).padStart(2, "0")}
                  title={FACTOR_INFO[code].title}
                  detail={FACTOR_INFO[code].detail}
                  icon={FACTOR_INFO[code].icon}
                />
              ))}
            </div>
          ) : (
            <p className="mt-6 text-sm leading-7 text-muted-foreground">
              아직 평소와 견주어 볼 만큼 기록이 쌓이지 않았어요. 오늘 하루를 남기는 것부터 시작해 봐요.
            </p>
          )}
        </div>
        <div className="border-t border-border pt-5 lg:mt-7 lg:border-t-0 lg:pt-0">
          <p className="text-xs tracking-[.04em] text-muted-foreground">04 · ONE SMALL THING</p>
          <div className="mt-4">
            {latest_risk ? (
              <Tag tone={riskIsHigh ? "ochre" : "sage"}>생활 흐름 변화 · {RISK_LABELS[latest_risk.level]}</Tag>
            ) : (
              <Tag tone="sage">기록을 모으는 중</Tag>
            )}
          </div>
          {latest_risk ? (
            <>
              <p className="mt-4 font-serif text-xl leading-8 text-[#49423b]">
                이번 주에는
                <br />
                하나만 덜어내도 괜찮아요.
              </p>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                중요도가 낮은 일정 한 개를 조정하거나, 오늘 10분의 빈 시간을 남겨보세요.
              </p>
              <TextButton onClick={() => go("plan")}>이번 주에 해보기</TextButton>
            </>
          ) : (
            <>
              <p className="mt-4 font-serif text-xl leading-8 text-[#49423b]">
                지금은 남기는 것만으로
                <br />
                충분해요.
              </p>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                잘 잤는지, 얼마나 쉬었는지만 적어두면 나중에 나를 이해하는 단서가 돼요.
              </p>
              <TextButton onClick={() => go("record")}>오늘 하루 남기기</TextButton>
            </>
          )}
        </div>
      </section>
    </>
  );
}
