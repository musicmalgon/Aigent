import { CalendarDays, ChevronRight, Clock3, Moon } from "lucide-react";
import { ChangeRow, Hairline, NoteMark, Tag, TextButton } from "../components/common";
import type { AppScreen } from "../types";

export function HomeView({ go, openRecord }: { go: (screen: AppScreen) => void; openRecord: () => void }) {
  return (
    <>
      <section className="grid gap-10 border-b border-border pb-11 lg:grid-cols-[minmax(0,1.22fr)_minmax(250px,.52fr)] lg:gap-16">
        <div className="pt-1">
          <p className="text-xs tracking-[.04em] text-muted-foreground">7월 18일, 금요일 · 이번 주의 관찰</p>
          <h1 className="mt-5 max-w-2xl font-serif text-[31px] leading-[1.5] tracking-[-.055em] text-[#35332f] sm:text-[39px]">
            지난 일주일, 잠드는 시간이 늦어지고
            <br className="hidden sm:block" /> 쉬는 시간이 줄었어요.
            <NoteMark />
          </h1>
          <p className="mt-5 max-w-xl text-[14px] leading-7 text-muted-foreground">
            변화가 이어진 지 7일째예요. 오늘 할 수 있는 한 가지를 남기고, 생활의 빈자리를 조금씩 되찾아 봐요.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
            <TextButton onClick={() => go("report")}>왜 달라졌는지 보기</TextButton>
            <button onClick={openRecord} className="text-sm text-muted-foreground underline underline-offset-4">
              오늘 기록 다시 보기
            </button>
          </div>
        </div>
        <div className="border-t border-border pt-5 lg:border-l lg:border-t-0 lg:pl-9 lg:pt-1">
          <p className="text-[11px] tracking-[.12em] text-muted-foreground">01 · TODAY</p>
          <p className="mt-4 font-serif text-[21px] leading-8 text-[#3c4540]">
            오늘을 남기면,
            <br />
            내일의 흐름이 보여요.
          </p>
          <Hairline className="my-5" />
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-sm text-muted-foreground">오늘의 기록</p>
              <p className="mt-1 text-sm leading-6 text-[#494741]">
                수면 · 휴식 · 마음을
                <br />2분 안에 남길 수 있어요.
              </p>
            </div>
            <span className="font-serif text-3xl text-[#d9a17d]">01</span>
          </div>
          <button onClick={() => go("record")} className="mt-5 inline-flex items-center gap-2 rounded-lg bg-[#68796b] px-3.5 py-2.5 text-sm font-semibold text-[#fffdf9]">
            오늘 하루 남기기 <ChevronRight size={15} />
          </button>
        </div>
      </section>

      <section className="py-12">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <p className="text-xs tracking-[.04em] text-muted-foreground">02 · RECENT WEEK</p>
            <h2 className="mt-3 font-serif text-[24px] tracking-[-.045em]">지난 7일의 생활 리듬</h2>
          </div>
          <p className="max-w-xs text-xs leading-5 text-muted-foreground">면접 준비가 시작된 화요일부터 잠드는 시간이 평소보다 늦어졌어요.</p>
        </div>
        <div className="relative mt-8 h-44 border-b border-border">
          <div className="absolute inset-x-0 top-[42%] border-t border-dashed border-[#bfc8c0]" />
          <span className="absolute right-0 top-[32%] bg-background px-2 text-[10px] text-muted-foreground">평소 수면 시간</span>
          <svg className="absolute inset-0 h-full w-full overflow-visible" viewBox="0 0 700 160" preserveAspectRatio="none" aria-label="최근 수면 시간 변화 그래프">
            <path d="M0 46 C63 42 78 48 117 53 S190 39 234 52 S305 69 350 75 S410 68 466 94 S530 121 584 112 S650 126 700 139" fill="none" stroke="#778A93" strokeWidth="2.1" />
            <circle cx="466" cy="94" r="4" fill="#D9A17D" />
            <circle cx="700" cy="139" r="4" fill="#BE765B" />
          </svg>
          <div className="absolute bottom-[-26px] left-0 right-0 flex justify-between text-[11px] text-muted-foreground">
            {["월 14", "화 15", "수 16", "목 17", "금 18", "토 19", "일 20"].map(x => (
              <span key={x}>{x}</span>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t border-border py-8">
        <button onClick={() => go("past")} className="flex w-full items-start justify-between gap-5 text-left">
          <div>
            <p className="text-xs tracking-[.04em] text-muted-foreground">지난 기록 이어보기</p>
            <p className="mt-3 font-serif text-lg leading-7">
              잠드는 시간이 늦었지만,
              <br className="sm:hidden" /> 오후에는 오래 쉬어갈 수 있었어요.
            </p>
            <p className="mt-2 text-xs text-muted-foreground">7월 17일 · 수면 5시간 40분 · 휴식 1시간 10분 · 무기력</p>
          </div>
          <ChevronRight className="mt-4 shrink-0 text-[#aaa197]" size={18} />
        </button>
      </section>

      <section className="grid gap-x-16 gap-y-10 border-t border-border py-12 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,.58fr)]">
        <div>
          <p className="text-xs tracking-[.04em] text-muted-foreground">03 · WHAT CHANGED</p>
          <h2 className="mt-3 font-serif text-[24px] tracking-[-.045em]">평소와 달라진 부분</h2>
          <div className="mt-6 divide-y divide-border border-y border-border">
            <ChangeRow index="01" title="수면 시간이 줄었어요" detail="평소 7시간 → 최근 4시간 30분" icon={Moon} />
            <ChangeRow index="02" title="쉴 틈이 적었어요" detail="평소 1시간 30분 → 최근 20분" icon={Clock3} />
            <ChangeRow index="03" title="일정이 조금 빽빽해졌어요" detail="향후 일주일 주요 일정 6개" icon={CalendarDays} />
          </div>
        </div>
        <div className="border-t border-border pt-5 lg:mt-7 lg:border-t-0 lg:pt-0">
          <p className="text-xs tracking-[.04em] text-muted-foreground">04 · ONE SMALL THING</p>
          <div className="mt-4">
            <Tag tone="ochre">변화를 살펴보는 중</Tag>
          </div>
          <p className="mt-4 font-serif text-xl leading-8 text-[#49423b]">
            이번 주에는
            <br />
            하나만 덜어내도 괜찮아요.
          </p>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">중요도가 낮은 일정 한 개를 조정하거나, 오늘 10분의 빈 시간을 남겨보세요.</p>
          <TextButton onClick={() => go("plan")}>이번 주에 해보기</TextButton>
        </div>
      </section>
    </>
  );
}
