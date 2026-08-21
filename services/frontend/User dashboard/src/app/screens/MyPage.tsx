import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import type { OverlayKind } from "../types";
import { getCurrentConsents } from "../api/consents";

// Consent.tsx의 CONSENT_ITEMS와 같은 개수(5개) -- 동의내역 요약에 "몇 개 중
// 몇 개"를 보여주기 위한 분모.
const TOTAL_CONSENT_ITEMS = 5;

export function MyPage({ open }: { open: (kind: OverlayKind) => void }) {
  // 예전엔 "연결 1개", "4개 항목"이 화면에 고정 문자열로 박혀 있었다.
  // 실제로는 연동이 하나도 연결돼 있지 않고(#M7 -- Google Calendar는 아직
  // 미리보기 전용) 동의도 항목마다 사용자가 실제로 고른 것과 다를 수
  // 있어서(#H1), 이 요약이 실제 상태와 어긋나 있었다(#M8). 동의내역만은
  // 서버에서 실제 granted 개수를 받아와 보여준다.
  const [grantedConsentCount, setGrantedConsentCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const consents = await getCurrentConsents();
        const granted = consents.filter(c => c.status === "granted").length;
        if (!cancelled) setGrantedConsentCount(granted);
      } catch {
        // 무시 -- 아래에서 요약 없이 표시됨 (거짓 숫자를 보여주는 것보다 낫다)
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const rows: [string, string, string, OverlayKind][] = [
    ["연동", "캘린더와 건강 기록을 연결해 입력을 줄여요.", "0개 연결됨", "integration"],
    [
      "동의내역",
      "내가 허용한 데이터 사용 범위를 확인해요.",
      grantedConsentCount === null ? "" : `${grantedConsentCount}/${TOTAL_CONSENT_ITEMS}개 항목`,
      "consent-history",
    ],
    ["개인정보 수정", "이름, 비밀번호와 계정 연결을 관리해요.", "", "account"],
  ];

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
