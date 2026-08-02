import { useState } from "react";
import { OnboardingFrame } from "../components/common";
import type { AppScreen, OnboardMode } from "../types";

const MODE_OPTIONS: [OnboardMode, string, string][] = [
  ["brief", "간단히 시작하기", "꼭 필요한 질문만 답하고 먼저 기록을 시작해요."],
  ["detailed", "자세히 기록하기", "지금의 생활 흐름을 조금 더 천천히 살펴봐요."],
];

export function Mode({ go, setMode }: { go: (screen: AppScreen) => void; setMode: (m: OnboardMode) => void }) {
  const [choice, setChoice] = useState<OnboardMode>("brief");

  return (
    <OnboardingFrame
      step="2 / 5"
      title={
        <>
          어떤 방식으로
          <br />
          시작해 볼까요?
        </>
      }
      description="둘 중 어느 쪽을 골라도, 기록을 이어가며 나에게 맞게 조정할 수 있어요."
    >
      <div className="divide-y divide-border border-y border-border">
        {MODE_OPTIONS.map(([id, title, detail]) => (
          <button key={id} onClick={() => setChoice(id)} className="flex w-full gap-4 py-5 text-left">
            <span className={`mt-0.5 grid size-5 place-items-center rounded-full border ${choice === id ? "border-[#68796b] bg-[#68796b] text-white" : "border-[#aaa197]"}`}>
              {choice === id && <span className="size-1.5 rounded-full bg-white" />}
            </span>
            <span>
              <strong className="text-sm font-medium">{title}</strong>
              <span className="mt-1 block text-xs leading-5 text-muted-foreground">{detail}</span>
            </span>
          </button>
        ))}
      </div>
      <button
        onClick={() => {
          setMode(choice);
          go("burnout");
        }}
        className="mt-7 rounded-lg bg-[#68796b] px-4 py-3 text-sm font-semibold text-white"
      >
        질문 이어가기
      </button>
    </OnboardingFrame>
  );
}
