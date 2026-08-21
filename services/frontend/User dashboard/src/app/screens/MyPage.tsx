import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import type { OverlayKind } from "../types";
import { getBehavioralRecordsRange, type BehavioralRecordRead } from "../api/behavioralRecords";

// 지금 실제로 연동 가능한 항목 수(Google Calendar, Samsung Health) -- 새 연동이
// 추가되면 이 숫자와 countConnectedIntegrations도 함께 늘려야 한다.
const TOTAL_INTEGRATIONS = 2;

// Samsung Health(Health Connect)가 실제로 값을 넣어준 적 있는지는 최근
// 생활기록의 source_by_field에 "health_platform"이 하나라도 있는지로
// 판단한다 -- 이미 있는 생활기록 조회 API 응답만으로 알 수 있어 새 백엔드가
// 필요 없다. Google Calendar는 실제 연동이 구현돼 있지 않으므로(연동 화면의
// 토글은 아직 로컬 UI 상태일 뿐 아무 데도 저장되지 않는다) 연동된 것처럼
// 세지 않는다 -- 실제로 연동되지 않은 걸 연동됐다고 보여주지 않기 위함이다.
function countConnectedIntegrations(records: BehavioralRecordRead[]): number {
  const samsungHealthConnected = records.some(record =>
    Object.values(record.source_by_field).includes("health_platform")
  );
  return samsungHealthConnected ? 1 : 0;
}

export function MyPage({ open }: { open: (kind: OverlayKind) => void }) {
  const [connectedCount, setConnectedCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getBehavioralRecordsRange()
      .then(records => {
        if (!cancelled) setConnectedCount(countConnectedIntegrations(records));
      })
      .catch(() => {
        // 조회 실패는 "연동 안 됨"으로 안전하게 보여준다 -- 마이페이지
        // 전체를 에러 화면으로 만들 정도의 정보는 아니다.
        if (!cancelled) setConnectedCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows: [string, string, string, OverlayKind][] = [
    [
      "연동",
      "캘린더와 건강 기록을 연결해 입력을 줄여요.",
      `${connectedCount ?? 0}/${TOTAL_INTEGRATIONS}`,
      "integration",
    ],
    ["동의내역", "내가 허용한 데이터 사용 범위를 확인해요.", "5개 항목", "consent-history"],
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
