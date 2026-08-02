import { NoteMark, Tag, TextButton } from "../components/common";
import type { AppScreen } from "../types";

const rows: [string, string, string, string][] = [
  ["수면", "7시간", "4시간 30분", "38"],
  ["공부 · 업무", "5시간", "9시간", "82"],
  ["휴식", "1시간 30분", "20분", "20"],
  ["감정 점수", "75점", "51점", "52"],
];

const suggestions: [string, string][] = [
  ["방해받지 않는 휴식 30분", "오늘 저녁, 알림을 잠시 꺼두기"],
  ["잠드는 시간을 조금 앞당기기", "평소보다 1시간 일찍 침대에 눕기"],
  ["가벼운 움직임 만들기", "산책이나 스트레칭 20분"],
];

export function ReportView({ go }: { go: (screen: AppScreen) => void }) {
  return (
    <section className="max-w-5xl">
      <p className="text-xs text-muted-foreground">생활 리포트 · 7월 12일 — 18일</p>
      <h1 className="mt-4 font-serif text-[31px] leading-[1.45] tracking-[-.05em]">
        잠과 휴식이 함께 줄어든 상태가
        <br />
        일주일째 이어지고 있어요.
        <NoteMark />
      </h1>
      <p className="mt-5 max-w-2xl text-sm leading-7 text-muted-foreground">
        최근 7일간 평균 수면 시간이 평소보다 2시간 30분 감소했고, 휴식 시간은 약 70% 줄었습니다. 주요 일정과 지친 감정을 남긴 날도 늘었어요.
      </p>
      <div className="mt-9 border-l-2 border-[#be765b] pl-3">
        <Tag tone="ochre">생활 흐름 변화 · 높음</Tag>
        <span className="ml-3 text-xs text-muted-foreground">기록을 바탕으로 한 참고 정보예요.</span>
      </div>
      <section className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div>
          <h2 className="font-serif text-xl">평소와 최근의 비교</h2>
          <div className="mt-5 divide-y divide-border border-y border-border">
            {rows.map(([label, base, recent, width]) => (
              <div className="grid grid-cols-[90px_1fr] gap-3 py-4" key={label}>
                <p className="text-sm">{label}</p>
                <div>
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">평소 {base}</span>
                    <span className="font-medium text-[#8d5541]">최근 {recent}</span>
                  </div>
                  <div className="mt-2 h-[3px] bg-[#e4dfd7]">
                    <div className="h-[3px] bg-[#778a93]" style={{ width: `${width}%` }} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <aside className="border-t border-border pt-5 lg:border-l lg:border-t-0 lg:pl-7">
          <p className="text-xs text-muted-foreground">기록에서 보인 변화</p>
          <blockquote className="mt-4 font-serif text-lg leading-8 text-[#504a43]">“면접 준비 때문에 계속 긴장되고 제대로 쉬지 못했다.”</blockquote>
          <p className="mt-3 text-xs text-muted-foreground">7월 16일에 남긴 기록</p>
        </aside>
      </section>
      <section className="mt-12 border-t border-border pt-8">
        <p className="text-xs text-muted-foreground">이번 주, 가볍게 시도해 볼 것</p>
        <div className="mt-5 divide-y divide-border border-y border-border">
          {suggestions.map(([x, y], i) => (
            <div className="flex items-center gap-4 py-4" key={x}>
              <span className="font-serif text-lg text-[#aaa197]">0{i + 1}</span>
              <div className="flex-1">
                <p className="text-sm font-medium">{x}</p>
                <p className="mt-1 text-xs text-muted-foreground">{y}</p>
              </div>
              <button className="text-xs font-semibold text-[#68796b]">추가</button>
            </div>
          ))}
        </div>
        <TextButton onClick={() => go("plan")}>이번 주에 해보기</TextButton>
      </section>
      <p className="mt-12 border-t border-border pt-5 text-xs leading-5 text-muted-foreground">이 결과는 생활 기록을 바탕으로 한 참고 정보이며, 의료적 진단을 제공하지 않습니다.</p>
    </section>
  );
}
