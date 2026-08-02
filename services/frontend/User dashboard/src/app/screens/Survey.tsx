import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Brand } from "../components/common";
import type { AppScreen, OnboardMode } from "../types";

const questions = [
  { title: "최근 잠은 어땠나요?", options: ["충분히 잤어요", "조금 부족했어요", "많이 부족했어요"], optional: false },
  { title: "쉬는 시간은 어느 정도였나요?", options: ["충분했어요", "조금 짧았어요", "거의 없었어요"], optional: false },
  { title: "공부 또는 업무 시간은 어땠나요?", options: ["평소와 비슷해요", "조금 길었어요", "많이 길었어요"], optional: false },
  { title: "이번 주 일정은 어떻게 느껴졌나요?", options: ["여유가 있었어요", "조금 빽빽했어요", "많이 빽빽했어요"], optional: false },
  { title: "운동이나 가벼운 움직임이 있었나요?", options: ["있었어요", "조금 있었어요", "없었어요"], optional: true },
  { title: "가장 자주 느낀 마음은 무엇인가요?", options: ["괜찮음", "지침", "무기력"], optional: false },
  { title: "스트레스는 어느 정도였나요?", options: ["낮았어요", "보통이었어요", "높았어요"], optional: false },
  { title: "피로감은 어느 정도였나요?", options: ["가벼웠어요", "조금 느꼈어요", "많이 느꼈어요"], optional: true },
];

export function Survey({ go, mode }: { go: (screen: AppScreen) => void; mode: OnboardMode }) {
  const activeQuestions = mode === "brief" ? questions.filter(q => q.title !== "이번 주 일정은 어떻게 느껴졌나요?") : questions;
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<string[]>(Array(activeQuestions.length).fill(""));
  const question = activeQuestions[index];
  const advance = () => (index === activeQuestions.length - 1 ? go("result") : setIndex(index + 1));

  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-2xl">
        <Brand />
        <div className="mt-16">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>시작 전 확인 · 4 / 5</span>
            <span>
              {index + 1} / {activeQuestions.length}
            </span>
          </div>
          <div className="mt-3 h-px bg-border">
            <div className="h-px bg-[#68796b] transition-all" style={{ width: `${((index + 1) / activeQuestions.length) * 100}%` }} />
          </div>
          <div className="mt-16">
            <p className="text-xs text-muted-foreground">{question.optional ? "건너뛸 수 있는 질문" : "생활 흐름을 위한 질문"}</p>
            <h1 className="mt-4 font-serif text-[30px] leading-[1.5] tracking-[-.05em]">{question.title}</h1>
            <div className="mt-9 divide-y divide-border border-y border-border">
              {question.options.map(option => (
                <button
                  onClick={() => setAnswers(value => value.map((x, i) => (i === index ? option : x)))}
                  key={option}
                  className="flex w-full items-center justify-between py-5 text-left text-sm"
                >
                  <span>{option}</span>
                  <span className={`grid size-5 place-items-center rounded-full border ${answers[index] === option ? "border-[#68796b] bg-[#68796b] text-white" : "border-[#aaa197]"}`}>
                    {answers[index] === option && <span className="size-1.5 rounded-full bg-white" />}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="mt-12 flex items-center justify-between">
            <button onClick={() => setIndex(Math.max(0, index - 1))} disabled={index === 0} className="inline-flex items-center gap-2 text-sm text-muted-foreground disabled:invisible">
              <ArrowLeft size={16} />
              이전
            </button>
            <div className="flex items-center gap-5">
              <button onClick={advance} className="text-sm text-muted-foreground">
                {question.optional ? "건너뛰기" : ""}
              </button>
              <button onClick={advance} disabled={!answers[index] && !question.optional} className="rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white disabled:bg-[#b7beb5]">
                {index === activeQuestions.length - 1 ? "결과 보기" : "다음"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
