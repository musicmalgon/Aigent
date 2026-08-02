import { pastRecords } from "../types";
import type { AppScreen } from "../types";

export function PastView({ openRecord, go }: { openRecord: () => void; go: (screen: AppScreen) => void }) {
  return (
    <section className="mx-auto max-w-4xl">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-xs text-muted-foreground">지난 기록</p>
          <h1 className="mt-4 font-serif text-[31px] tracking-[-.05em]">하루하루 쌓인 흐름들</h1>
        </div>
        <button onClick={() => go("record")} className="text-sm text-[#536458] underline underline-offset-4">
          오늘 남기기
        </button>
      </div>
      <div className="mt-10 divide-y divide-border border-y border-border">
        {pastRecords.map(record => (
          <button onClick={openRecord} className="block w-full py-7 text-left first:pt-5" key={record.date}>
            <p className="text-xs text-muted-foreground">{record.date}</p>
            <p className="mt-3 max-w-xl font-serif text-lg leading-8 text-[#4c4842]">{record.summary}</p>
            <div className="mt-3 flex items-center justify-between gap-4">
              <p className="text-xs text-muted-foreground">{record.meta}</p>
              <span className="shrink-0 text-xs text-[#536458]">자세히 보기</span>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
