import { useState } from "react";
import { Brand, LikertScale } from "../../components/common";

export function BurnoutSubscaleScreen({
  nameKo,
  nameEn,
  description,
  topNote,
  questions,
  subStep,
  totalSubSteps,
  onNext,
  onBack,
  submitting,
  notice,
}: {
  nameKo: string;
  nameEn: string;
  description: string;
  /** 화면 맨 위, 브랜드 로고 아래에 노출되는 안내 문구 (예: 탈진 화면의 도입부 안내) */
  topNote?: string;
  questions: string[];
  subStep: number; // 1-based
  totalSubSteps: number;
  /** 리커트 응답(0~4)을 그대로 넘긴다 -- 채점은 BurnoutFlow가 모아서 한다 */
  onNext: (answers: number[]) => void;
  onBack?: () => void;
  /** 마지막 영역에서 결과를 저장하는 동안 버튼을 잠근다 */
  submitting?: boolean;
  /** 저장 실패처럼 사용자를 붙잡아두지 않는 안내 문구 */
  notice?: string;
}) {
  const total = questions.length;
  const [answers, setAnswers] = useState<(number | null)[]>(Array(total).fill(null));
  const answered = answers.filter(a => a !== null).length;
  const allAnswered = answered === total;

  const handleSelect = (qi: number, v: number) => setAnswers(prev => prev.map((a, i) => (i === qi ? v : a)));

  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-2xl">
        <Brand />
        {topNote && <p className="mt-6 max-w-xl text-sm leading-7 text-muted-foreground">{topNote}</p>}
        <div className="mt-12">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>시작 전 확인 · 번아웃 자가 진단</span>
            <span>{subStep} / {totalSubSteps}</span>
          </div>
          <div className="mt-3 h-px bg-border">
            <div className="h-px bg-[#68796b] transition-all" style={{ width: `${(subStep / totalSubSteps) * 100}%` }} />
          </div>
        </div>

        <h1 className="mt-9 font-serif text-[26px] leading-[1.5] tracking-[-.05em]">
          {nameKo} <span className="text-muted-foreground">({nameEn})</span>
        </h1>
        <p className="mt-4 max-w-xl text-sm leading-7 text-muted-foreground">{description}</p>

        <div className="mt-6 flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{answered} / {total} 응답됨</span>
          <div className="flex gap-1">
            {answers.map((a, i) => (
              <span key={i} className={`h-1 w-5 rounded-full transition-colors duration-300 ${a !== null ? "bg-[#68796b]" : "bg-[#e4dfd7]"}`} />
            ))}
          </div>
        </div>
        <div className="mt-2 h-px bg-border">
          <div className="h-px bg-[#68796b] transition-all duration-500" style={{ width: `${(answered / total) * 100}%` }} />
        </div>

        <div className="mt-8 space-y-4">
          {questions.map((q, qi) => (
            <div
              key={qi}
              className={`rounded-2xl border bg-[#fffdf9] px-6 py-6 transition-colors duration-200 sm:px-8 ${
                answers[qi] !== null ? "border-[#c8d5c9]" : "border-border"
              }`}
            >
              <div className="flex items-start gap-3.5">
                <span className="mt-0.5 shrink-0 font-serif text-sm text-[#aaa197]">{String(qi + 1).padStart(2, "0")}</span>
                <p className="font-serif text-[17px] leading-[1.7] tracking-[-.03em] text-[#35332f]">{q}</p>
              </div>
              <LikertScale value={answers[qi]} onChange={v => handleSelect(qi, v)} />
            </div>
          ))}
        </div>

        <div className="mt-10 flex items-center justify-between border-t border-border pt-7">
          {onBack ? (
            <button onClick={onBack} className="text-xs text-muted-foreground underline underline-offset-4">
              이전 영역
            </button>
          ) : (
            <p className="text-xs text-muted-foreground">{allAnswered ? "모든 문항에 응답했어요." : `${total - answered}개 문항이 남았어요.`}</p>
          )}
          <button
            // 모든 문항에 응답해야 버튼이 열리므로 이 시점의 answers엔 null이 없다
            onClick={() => onNext(answers.filter((a): a is number => a !== null))}
            disabled={!allAnswered || submitting}
            className="rounded-lg bg-[#68796b] px-5 py-2.5 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:bg-[#b7beb5]"
          >
            {submitting ? "저장 중..." : "다음"}
          </button>
        </div>
        {notice && <p className="mt-4 text-right text-xs text-muted-foreground">{notice}</p>}
      </div>
    </main>
  );
}