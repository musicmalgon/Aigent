import { useEffect, useState } from "react";
import { Brand, NoteMark, SummaryLine, Tag, TextButton } from "../components/common";
import type { AppScreen } from "../types";
import { getKBatResult, type KBatResultResponse, type KBatRiskLevel } from "../api/assessments";
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

export function BurnoutResultView({ go }: { go: (screen: AppScreen) => void }) {
  const [data, setData] = useState<KBatResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

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
            <p className="text-xs tracking-[.08em] text-muted-foreground">번아웃 자가진단 · 설문 완료됨</p>
            <h1 className="mt-5 font-serif text-[30px] leading-[1.55] tracking-[-.05em]">
              아직 충분한 기록이
              <br />
              쌓이지 않았어요.
              <NoteMark />
            </h1>
            <p className="mt-5 text-sm leading-7 text-muted-foreground">
              설문 결과와 일상기록을 함께 봐야 더 정확해요. 일상기록을 {data.minimum_required_days}일 동안 작성한 후 다시 확인해 주세요.
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

  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-2xl">
        <Brand />
        <div className="mt-16 max-w-xl">
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

          <div className="mt-9 flex flex-wrap gap-5">
            <TextButton onClick={() => go("home")}>홈으로 돌아가기</TextButton>
          </div>
          <p className="mt-10 border-t border-border pt-5 text-xs leading-5 text-muted-foreground">
            이 결과는 설문 응답과 최근 일상기록을 바탕으로 한 참고 정보이며, 의료적 진단이 아닙니다.
          </p>
        </div>
      </div>
    </main>
  );
}
