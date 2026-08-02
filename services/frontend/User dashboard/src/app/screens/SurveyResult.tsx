import { Brand, NoteMark, SummaryLine } from "../components/common";
import type { AppScreen } from "../types";

export function SurveyResult({ go }: { go: (screen: AppScreen) => void }) {
  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-3xl">
        <Brand />
        <div className="mt-20 max-w-2xl">
          <p className="text-xs tracking-[.08em] text-muted-foreground">처음의 관찰 · 설문 응답 기준</p>
          <h1 className="mt-5 font-serif text-[32px] leading-[1.55] tracking-[-.055em]">
            최근에는 쉬는 시간보다
            <br />
            해야 할 일이 조금 더 앞에 있었어요.
            <NoteMark />
          </h1>
          <p className="mt-5 text-sm leading-7 text-muted-foreground">
            지금의 답변을 바탕으로 한 첫 번째 관찰이에요. 기록이 쌓이면 나만의 평소 흐름과 최근 변화를 비교할 수 있어요.
          </p>
          <div className="mt-10 divide-y divide-border border-y border-border">
            <SummaryLine label="눈에 띈 흐름" value="휴식 시간이 짧고, 일정 부담이 있었어요." />
            <SummaryLine label="처음 제안" value="오늘, 10분의 빈 시간을 먼저 남겨보세요." />
          </div>
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
