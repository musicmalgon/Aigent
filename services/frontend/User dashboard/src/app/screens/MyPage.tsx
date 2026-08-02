import { ChevronRight } from "lucide-react";
import type { OverlayKind } from "../types";

const rows: [string, string, string, OverlayKind][] = [
  ["연동", "캘린더와 건강 기록을 연결해 입력을 줄여요.", "연결 1개", "integration"],
  ["동의내역", "내가 허용한 데이터 사용 범위를 확인해요.", "4개 항목", "consent-history"],
  ["개인정보 수정", "이름, 비밀번호와 계정 연결을 관리해요.", "", "account"],
];

export function MyPage({ open }: { open: (kind: OverlayKind) => void }) {
  return (
    <section className="mx-auto max-w-4xl">
      <p className="text-xs text-muted-foreground">마이페이지</p>
      <h1 className="mt-4 font-serif text-[31px] tracking-[-.05em]">내 기록은 내가 결정해요</h1>
      <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">기록과 계정에 관한 선택을 한곳에서 편하게 확인할 수 있어요.</p>
      <div className="mt-10 divide-y divide-border border-y border-border">
        {rows.map(([title, detail, meta, kind]) => (
          <button onClick={() => open(kind)} className="flex w-full items-center gap-4 py-6 text-left" key={title}>
            <div className="flex-1">
              <p className="text-sm font-medium">{title}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
            </div>
            <span className="text-xs text-muted-foreground">{meta}</span>
            <ChevronRight size={16} className="text-[#aaa197]" />
          </button>
        ))}
      </div>
    </section>
  );
}
