import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Field, Integration, SummaryLine } from "../components/common";
import type { AppScreen, OverlayKind } from "../types";

export function OverlayContent({ kind, close, go }: { kind: OverlayKind; close: () => void; go: (screen: AppScreen) => void }) {
  const [sent, setSent] = useState(false);
  const [connected, setConnected] = useState(false);

  if (kind === "forgot")
    return (
      <>
        <p className="text-sm leading-6 text-muted-foreground">가입할 때 사용한 이메일을 입력하면 비밀번호를 다시 설정할 수 있는 안내를 보내드려요.</p>
        {sent ? (
          <p className="mt-7 font-serif text-lg leading-8">입력한 이메일로 비밀번호를 다시 설정할 수 있는 안내를 보냈어요.</p>
        ) : (
          <>
            <Field label="이메일" placeholder="name@example.com" type="email" />
            <button onClick={() => setSent(true)} className="mt-7 rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white">
              안내 보내기
            </button>
          </>
        )}
      </>
    );

  if (kind === "record")
    return (
      <>
        <p className="text-xs text-muted-foreground">7월 17일 목요일</p>
        <h3 className="mt-3 font-serif text-xl leading-8">
          잠드는 시간이 늦었지만,
          <br />
          오후에는 오래 쉬어갈 수 있었어요.
        </h3>
        <div className="mt-6 divide-y divide-border border-y border-border">
          <SummaryLine label="수면" value="5시간 40분 · 직접 입력" />
          <SummaryLine label="휴식" value="1시간 10분 · 직접 수정됨" />
          <SummaryLine label="공부 · 업무" value="7시간 30분" />
          <SummaryLine label="운동" value="산책 20분" />
          <SummaryLine label="일정 부담" value="조금 빽빽했어요" />
          <SummaryLine label="오늘의 마음" value="무기력" />
        </div>
        <p className="mt-6 text-sm leading-6 text-muted-foreground">“오후에는 계획을 조금 미루고, 집 근처를 걸었다.”</p>
        <p className="mt-4 text-xs text-muted-foreground">데이터 출처 · 직접 입력</p>
        <button
          onClick={() => {
            close();
            go("record");
          }}
          className="mt-7 text-sm text-[#536458] underline underline-offset-4"
        >
          이 기록 수정하기
        </button>
      </>
    );

  if (kind === "integration")
    return (
      <>
        <p className="text-sm leading-6 text-muted-foreground">연동된 기록도 직접 수정한 값이 우선해요.</p>
        <Integration name="Google Calendar" detail="일정 개수와 바쁜 시간대를 기록에 참고해요." connected={connected} setConnected={setConnected} />
        <Integration name="Samsung Health" detail="수면과 활동 기록을 오늘 기록에 가져와요." connected={false} setConnected={() => {}} />
        <p className="mt-6 text-xs leading-5 text-muted-foreground">실제 연결 기능은 준비 중이에요. 현재 화면에서는 연결 흐름만 미리 볼 수 있어요.</p>
      </>
    );

  if (kind === "consent-history")
    return (
      <div className="divide-y divide-border border-y border-border">
        {(
          [
            ["서비스 이용약관", "필수 · 2026. 7. 18"],
            ["개인정보 수집 및 이용", "필수 · 2026. 7. 18"],
            ["생활·건강 데이터 활용", "필수 · 2026. 7. 18"],
            ["생활 흐름 분석 활용", "필수 · 2026. 7. 18"],
            ["외부 서비스 연동", "선택 · 동의 안 함"],
          ] as const
        ).map(([x, y]) => (
          <div className="flex items-center justify-between gap-4 py-4" key={x}>
            <div>
              <p className="text-sm">{x}</p>
              <p className="mt-1 text-xs text-muted-foreground">{y}</p>
            </div>
            <button className="text-xs text-[#536458] underline underline-offset-4">자세히</button>
          </div>
        ))}
      </div>
    );

  if (kind === "account")
    return (
      <>
        <div className="divide-y divide-border border-y border-border">
          <button className="flex w-full items-center justify-between py-5 text-left">
            <span>
              <strong className="block text-sm font-medium">이름 변경</strong>
              <span className="mt-1 block text-xs text-muted-foreground">현재 이름 · 지민</span>
            </span>
            <ChevronRight size={16} />
          </button>
          <button className="flex w-full items-center justify-between py-5 text-left">
            <span>
              <strong className="block text-sm font-medium">비밀번호 변경</strong>
              <span className="mt-1 block text-xs text-muted-foreground">안전하게 계정을 관리해요.</span>
            </span>
            <ChevronRight size={16} />
          </button>
          <button className="flex w-full items-center justify-between py-5 text-left">
            <span>
              <strong className="block text-sm font-medium">계정 연결</strong>
              <span className="mt-1 block text-xs text-muted-foreground">Google · 연결 안 됨</span>
            </span>
            <ChevronRight size={16} />
          </button>
        </div>
        <div className="mt-10 border-t border-border pt-5">
          <p className="text-sm text-[#8d5541]">계정 삭제</p>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">계정을 삭제하면 지금까지의 기록과 연결 정보도 함께 사라져요.</p>
          <button className="mt-4 text-xs text-[#8d5541] underline underline-offset-4">삭제 방법 확인하기</button>
        </div>
      </>
    );

  return <p className="text-sm text-muted-foreground">이 항목의 내용을 확인할 수 있어요. 동의 범위는 언제든 마이페이지에서 다시 살펴볼 수 있어요.</p>;
}
