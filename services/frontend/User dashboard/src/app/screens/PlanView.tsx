import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { CheckBox } from "../components/common";

const goals: [string, string][] = [
  ["방해받지 않는 휴식 30분", "오늘 저녁"],
  ["가벼운 산책 20분", "토요일 오후"],
  ["잠드는 시간을 조금 앞당기기", "매일 밤"],
];

export function PlanView() {
  const [done, setDone] = useState([false, false, false]);
  return (
    <section className="mx-auto max-w-4xl">
      <p className="text-xs text-muted-foreground">이번 주의 회복 계획</p>
      <h1 className="mt-4 font-serif text-[31px] tracking-[-.05em]">할 수 있는 것만 골라볼까요?</h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">계획은 나를 재촉하는 약속이 아니라, 나를 돌보는 작은 여백이에요.</p>
      <div className="mt-10 divide-y divide-border border-y border-border">
        {goals.map(([title, time], i) => (
          <button onClick={() => setDone(d => d.map((x, j) => (j === i ? !x : x)))} className="flex w-full items-center gap-4 py-5 text-left" key={title}>
            <CheckBox checked={done[i]} />
            <div className="flex-1">
              <p className="text-sm font-medium">{title}</p>
              <p className="mt-1 text-xs text-muted-foreground">{time} · 10분부터 시작해도 괜찮아요</p>
            </div>
            <ChevronRight size={16} className="text-[#aaa197]" />
          </button>
        ))}
      </div>
      <div className="mt-9 grid gap-6 border-t border-border pt-6 sm:grid-cols-2">
        <div>
          <p className="text-xs text-muted-foreground">알림 시간</p>
          <p className="mt-2 text-sm">오후 8:30</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">목표 기간</p>
          <p className="mt-2 text-sm">7월 21일 — 27일</p>
        </div>
      </div>
      <button className="mt-9 rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white">이번 주에 해보기</button>
    </section>
  );
}
