import { Brand, NoteMark, SummaryLine } from "../components/common";
import type { AppScreen } from "../types";
import type { DimensionScores } from "../api/assessments";

type SurveyDimension = "exhaustion" | "academic_burden" | "occupational_burden" | "recovery_difficulty";

const SURVEY_DIMENSIONS: SurveyDimension[] = [
  "exhaustion",
  "academic_burden",
  "occupational_burden",
  "recovery_difficulty",
];

// 차원마다 부담도 3단계(낮음 / 조금 / 높음)로 문구를 나눠둔다.
// 같은 차원이 걸려도 점수에 따라 다른 문장이 나오도록 하기 위한 것.
const DIMENSION_COPY: Record<SurveyDimension, { headline: [string, string]; flows: [string, string, string]; suggestions: [string, string, string] }> = {
  exhaustion: {
    headline: ["마음의 에너지가", "조금씩 줄어들고 있었어요."],
    flows: [
      "마음 상태에는 아직 여유가 남아 있었어요.",
      "지치는 느낌이 조금씩 쌓이고 있었어요.",
      "마음이 많이 지쳐 있다고 답해주셨어요.",
    ],
    suggestions: [
      "지금의 리듬을 며칠만 더 기록해 봐요.",
      "오늘, 아무것도 하지 않는 10분을 남겨보세요.",
      "오늘은 하나만 덜어내도 괜찮아요. 가장 미룰 수 있는 일부터요.",
    ],
  },
  academic_burden: {
    headline: ["해야 할 공부가", "조금 더 앞에 있었어요."],
    flows: [
      "공부량은 평소와 비슷하게 유지되고 있었어요.",
      "해야 할 공부와 일정이 조금씩 늘고 있었어요.",
      "공부와 일정 부담이 꽤 크게 느껴지고 있었어요.",
    ],
    suggestions: [
      "지금 흐름을 며칠 더 남겨두면 비교가 쉬워져요.",
      "이번 주 할 일 중 하나는 다음 주로 미뤄봐요.",
      "가장 급하지 않은 일정 하나를 오늘 조정해 보세요.",
    ],
  },
  occupational_burden: {
    headline: ["해야 할 일이", "조금 더 앞에 있었어요."],
    flows: [
      "업무량은 평소와 비슷하게 유지되고 있었어요.",
      "업무와 일정이 조금씩 늘고 있었어요.",
      "업무와 일정 부담이 꽤 크게 느껴지고 있었어요.",
    ],
    suggestions: [
      "지금 흐름을 며칠 더 남겨두면 비교가 쉬워져요.",
      "오늘 처리할 일 중 하나는 내일로 넘겨봐요.",
      "가장 급하지 않은 일정 하나를 오늘 조정해 보세요.",
    ],
  },
  recovery_difficulty: {
    headline: ["쉬어가는 시간이", "조금 뒤로 밀려 있었어요."],
    flows: [
      "잠과 쉬는 시간은 그런대로 지켜지고 있었어요.",
      "쉬어가는 시간이 조금씩 짧아지고 있었어요.",
      "잠과 휴식이 많이 밀려 있었어요.",
    ],
    suggestions: [
      "지금의 수면 시간을 그대로 지켜봐요.",
      "오늘, 10분의 빈 시간을 먼저 남겨보세요.",
      "오늘은 평소보다 30분 일찍 잠자리에 들어보는 건 어떨까요.",
    ],
  },
};

const CALM_HEADLINE: [string, string] = ["지금은 큰 무리 없이", "하루를 보내고 계신 것 같아요."];
const EMPTY_HEADLINE: [string, string] = ["아직 분석할 데이터가", "부족해요."];

/** 0~1 부담도를 문구 강도 3단계로 나눈다. */
function band(score: number): 0 | 1 | 2 {
  if (score < 0.34) return 0;
  return score < 0.67 ? 1 : 2;
}

export function SurveyResult({ go, dimensions }: { go: (screen: AppScreen) => void; dimensions: DimensionScores | null }) {
  // 응답하지 않은 차원은 null로 오므로 점수가 있는 것만 남겨 높은 순으로 본다
  const scored = SURVEY_DIMENSIONS.map(key => ({ key, score: dimensions?.[key] }))
    .filter((entry): entry is { key: SurveyDimension; score: number } => typeof entry.score === "number")
    .sort((a, b) => b.score - a.score);

  const top = scored[0];
  // 두 번째 차원도 뚜렷하게 높을 때만 같이 언급한다
  const second = scored[1] && scored[1].score >= 0.5 ? scored[1] : null;

  const headline = !top ? EMPTY_HEADLINE : band(top.score) === 0 ? CALM_HEADLINE : DIMENSION_COPY[top.key].headline;

  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-3xl">
        <Brand />
        <div className="mt-20 max-w-2xl">
          <p className="text-xs tracking-[.08em] text-muted-foreground">처음의 관찰 · 설문 응답 기준</p>
          <h1 className="mt-5 font-serif text-[32px] leading-[1.55] tracking-[-.055em]">
            {headline[0]}
            <br />
            {headline[1]}
            <NoteMark />
          </h1>
          <p className="mt-5 text-sm leading-7 text-muted-foreground">
            {top
              ? "지금의 답변을 바탕으로 한 첫 번째 관찰이에요. 기록이 쌓이면 나만의 평소 흐름과 최근 변화를 비교할 수 있어요."
              : "설문 응답을 받지 못해서 아직 보여드릴 관찰이 없어요. 오늘 하루를 기록하는 것부터 시작해 봐요."}
          </p>
          {top && (
            <div className="mt-10 divide-y divide-border border-y border-border">
              <SummaryLine label="눈에 띈 흐름" value={DIMENSION_COPY[top.key].flows[band(top.score)]} />
              {second && <SummaryLine label="함께 본 흐름" value={DIMENSION_COPY[second.key].flows[band(second.score)]} />}
              <SummaryLine label="처음 제안" value={DIMENSION_COPY[top.key].suggestions[band(top.score)]} />
            </div>
          )}
          <button onClick={() => go("home")} className="mt-9 rounded-lg bg-[#68796b] px-4 py-3 text-sm font-semibold text-white">
            오늘 하루 남기기
          </button>
          <p className="mt-10 border-t border-border pt-5 text-xs leading-5 text-muted-foreground">
            이 내용은 설문 응답을 바탕으로 한 초기 참고 정보이며, 의료적 진단이 아닙니다.
          </p>
        </div>
      </div>
    </main>
  );
}
