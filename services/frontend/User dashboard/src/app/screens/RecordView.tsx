import { useState } from "react";
import { ArrowRight, Pencil } from "lucide-react";
import { EMOTION_DISPLAY_LABELS } from "../types";
import { Hairline, SummaryLine, TextButton } from "../components/common";
import type { AppScreen } from "../types";

export function RecordView({ go, editing = false }: { go: (screen: AppScreen) => void; editing?: boolean }) {
  const [step, setStep] = useState(1);
  const [emotion, setEmotion] = useState("지침");
  const [saved, setSaved] = useState(false);
  const [source, setSource] = useState("직접 입력");

  if (saved) {
    return (
      <section className="mx-auto max-w-3xl">
        <p className="text-xs text-muted-foreground">오늘의 기록 · 7월 18일</p>
        <h1 className="mt-4 font-serif text-[31px] leading-[1.5] tracking-[-.05em]">
          오늘은 잠이 조금 부족했지만,
          <br />
          잠시 쉬어간 시간은 어제보다 늘었어요.
        </h1>
        <p className="mt-5 text-sm leading-7 text-muted-foreground">오늘 남긴 기록을 바탕으로 한 하루의 요약이에요. 필요하면 언제든 고칠 수 있어요.</p>
        <div className="mt-9 divide-y divide-border border-y border-border">
          <SummaryLine label="수면" value="4시간 30분 · 직접 수정됨" />
          <SummaryLine label="휴식" value="20분 · 직접 입력" />
          <SummaryLine label="오늘의 마음" value={emotion} />
        </div>
        <div className="mt-8 flex flex-wrap gap-5">
          <button onClick={() => setSaved(false)} className="text-sm text-[#536458] underline underline-offset-4">
            기록 수정하기
          </button>
          <TextButton onClick={() => go("home")}>홈으로 돌아가기</TextButton>
        </div>
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-3xl">
      <p className="text-xs text-muted-foreground">오늘의 기록 · 7월 18일</p>
      <h1 className="mt-4 font-serif text-[31px] tracking-[-.05em]">{editing ? "기록을 다시 살펴볼까요?" : "오늘 하루를 남겨볼까요?"}</h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">정확하지 않아도 괜찮아요. 기억나는 만큼만 적어 주세요.</p>
      <div className="mt-9 flex items-center gap-3 text-xs">
        <span className="text-[#68796b]">01 생활</span>
        <span className="h-px w-10 bg-border" />
        <span className={step === 2 ? "text-[#68796b]" : "text-muted-foreground"}>02 마음</span>
      </div>
      <Hairline className="mt-3" />
      <div className="mt-7">
        {step === 1 ? (
          <>
            <p className="text-xs leading-5 text-muted-foreground">연동된 기록도 오늘의 상태에 맞게 직접 고칠 수 있어요.</p>
            <div className="mt-5 grid gap-x-10 border-b border-border sm:grid-cols-2">
              {(
                [
                  ["수면 시간", "4시간 30분", true],
                  ["휴식 시간", "20분", true],
                  ["공부 · 업무 시간", "9시간", false],
                  ["운동 시간", "20분", false],
                  ["오늘의 일정 부담", "조금 빽빽했어요", false],
                ] as const
              ).map(([label, value, integrated], i) => (
                <div key={String(label)} className={`flex items-center justify-between border-t border-border py-4 ${i === 0 ? "sm:border-t-0" : ""}`}>
                  <div>
                    <p className="text-sm text-muted-foreground">{label}</p>
                    {Boolean(integrated) && (
                      <button onClick={() => setSource(source === "직접 입력" ? "직접 수정됨" : "직접 입력")} className="mt-1 text-[11px] text-[#5a7160] underline underline-offset-2">
                        {source}
                      </button>
                    )}
                  </div>
                  <label className="flex items-center gap-2">
                    <input aria-label={`${label} 수정`} defaultValue={String(value)} className="w-28 border-b border-transparent bg-transparent py-1 text-right text-sm font-medium outline-none focus:border-[#68796b]" />
                    <Pencil size={14} strokeWidth={1.5} className="text-muted-foreground" />
                  </label>
                </div>
              ))}
            </div>
            <button onClick={() => setStep(2)} className="mt-8 inline-flex items-center gap-2 rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white">
              다음 <ArrowRight size={15} />
            </button>
          </>
        ) : (
          <>
            <p className="font-serif text-xl">오늘의 마음은 어땠나요?</p>
            <div className="mt-5 flex flex-wrap gap-x-6 gap-y-4">
              {["편안함", "괜찮음", "지침", "불안함", "상처", "압도됨"].map(value => (
                <button
                  onClick={() => setEmotion(EMOTION_DISPLAY_LABELS[value] ?? value)}
                  className={`border-b pb-1 text-sm ${emotion === (EMOTION_DISPLAY_LABELS[value] ?? value) ? "border-[#be765b] font-semibold text-[#8d5541]" : "border-transparent text-muted-foreground"}`}
                  key={value}
                >
                  {emotion === (EMOTION_DISPLAY_LABELS[value] ?? value) && "· "}
                  {EMOTION_DISPLAY_LABELS[value] ?? value}
                </button>
              ))}
            </div>
            <label className="mt-9 block text-sm text-muted-foreground">
              오늘 컨디션에 영향을 준 일이 있었나요?
              <textarea
                defaultValue="면접 준비 때문에 계속 긴장되고 제대로 쉬지 못했다."
                className="mt-3 min-h-28 w-full border-y border-border bg-transparent py-3 text-sm leading-6 text-foreground outline-none focus:border-[#68796b]"
              />
            </label>
            <button onClick={() => setSaved(true)} className="mt-7 rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white">
              기록 남기기
            </button>
          </>
        )}
      </div>
    </section>
  );
}
